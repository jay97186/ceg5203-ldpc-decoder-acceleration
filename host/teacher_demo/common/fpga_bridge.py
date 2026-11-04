"""XSDB/JTAG bridge. Results always come from the physical FPGA via DMA."""
from pathlib import Path
import json
import os
import subprocess
import time

ROOT = Path(__file__).resolve().parent
MAGIC = 0x4C445055

class Cancelled(Exception):
    pass

def load_config():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    for key in ("firmware", "bitstream", "fsbl"):
        value = Path(config[key])
        config[key] = str(value if value.is_absolute() else ROOT / value)
    return config

def literal(value):
    value = str(value).replace("\\", "/")
    return '"' + value.replace('"', '\\"').replace("$", "\\$").replace("[", "\\[").replace("]", "\\]") + '"'

def _process(script, directory, event, cancel=None):
    env = os.environ.copy()
    env["LDPC_XSDB"] = load_config()["xsdb"]
    env["LDPC_TCL"] = str(script)
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
               "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); $OutputEncoding = [Console]::OutputEncoding; & $env:LDPC_XSDB $env:LDPC_TCL; exit $LASTEXITCODE"]
    lines = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        for line in process.stdout:
            lines.append(line)
            if cancel and cancel.is_set():
                (directory / "cancel.flag").touch()
            clean = line.strip()
            if clean.startswith("UI|"):
                parts = clean.split("|", 2)
                event(parts[1], parts[2] if len(parts) > 2 else "")
        code = process.wait()
    (directory / "xsdb.log").write_text("".join(lines), encoding="utf-8")
    combined = "".join(lines)
    # XSDB sometimes prints a Tcl error but still returns process exit code 0.
    # Treat its explicit error marker as failure instead of "Incomplete results".
    if code or "UI_ERROR:" in combined:
        if cancel and cancel.is_set():
            raise Cancelled("Run cancelled")
        if "no targets found" in combined:
            raise RuntimeError(
                "Cortex-A53 #0 was not detected by JTAG.\n"
                "Check board power and JTAG USB, then start Start_HW_Server.cmd.\n"
                "Close any stale UI window and launch Start_UI.cmd from Windows File Explorer.\n\n"
                + "".join(lines[-10:]))
        raise RuntimeError("JTAG operation failed.\n" + "".join(lines[-18:]))
    return "".join(lines)

def probe(event=lambda *_: None):
    directory = ROOT / "runs" / "connection"
    directory.mkdir(parents=True, exist_ok=True)
    config = load_config()
    if not Path(config["xsdb"]).is_file():
        raise FileNotFoundError("XSDB was not found. Set the Vitis installation path in config.json.")
    script = directory / "probe.tcl"
    script.write_text(
        "connect -url " + literal(config["hw_server_url"]) + "\n"
        'puts [targets]\n'
        'targets -set -filter {name =~ "Cortex-A53 #0"}\n'
        'puts "UI|connected|Cortex-A53 #0 / JTAG"\n'
        'disconnect\nexit\n', encoding="utf-8")
    output = _process(script, directory, event)
    if "UI|connected|" not in output:
        raise RuntimeError("JTAG did not report a successful connection.\n" + output[-1800:])
    return output

def run_hardware(llr, limits, directory, initialize, event, cancel):
    config = load_config()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    frames = int(llr.shape[0])
    if llr.shape != (frames, 384) or not 1 <= frames <= 8192:
        raise ValueError("The hardware supports 1..8192 codewords of 384 bits each.")
    if not limits or any(not 0 <= int(x) <= 20 for x in limits):
        raise ValueError("Iteration limits must be between 0 and 20.")
    for key in ("xsdb", "firmware"):
        if not Path(config[key]).is_file():
            raise FileNotFoundError(config[key])
    llr.astype("<f4").tofile(directory / "input_llr.f32")
    attach = bool(config.get("attach_running", False))
    initialization = ""
    if initialize and not attach:
        for key in ("bitstream", "fsbl"):
            if not Path(config[key]).is_file():
                raise FileNotFoundError(config[key])
        initialization = f'''
puts "UI|stage|Initializing PS, bitstream and FSBL"
targets -set -filter {{name =~ "PSU"}}
rst -system
after 1000
targets -set -filter {{name =~ "PL"}}
fpga -file {literal(config["bitstream"])}
targets -set -filter {{name =~ "Cortex-A53 #0"}}
rst -processor -clear-registers
dow {literal(config["fsbl"])}
set fsbl_bp [bpadd -addr &XFsbl_Exit]
con -block -timeout 45
bpremove $fsbl_bp
'''
    startup = "" if attach else f'''
catch {{stop}}
catch {{bpremove -all}}
{initialization}
emit stage "Loading ARM controller firmware"
targets -set -filter {{name =~ "Cortex-A53 #0"}}
rst -processor -clear-registers
dow {literal(config["firmware"])}
con
'''
    script_text = f'''
# Physical DDR access via PSU; do not halt the decoder for polling.
proc bridge_mrd {{args}} {{
 targets -set -filter {{name =~ "PSU"}}
 try {{return [mrd {{*}}$args]}} finally {{
  targets -set -filter {{name =~ "Cortex-A53 #0"}}
 }}
}}
proc bridge_mwr {{args}} {{
 targets -set -filter {{name =~ "PSU"}}
 try {{return [mwr {{*}}$args]}} finally {{
  targets -set -filter {{name =~ "Cortex-A53 #0"}}
 }}
}}
proc emit {{kind message}} {{ puts "UI|$kind|$message"; flush stdout }}
proc check_cancel {{}} {{
    if {{[file exists {literal(directory / "cancel.flag")}]}} {{ error "CANCELLED" }}
}}
if {{[catch {{
connect -url {literal(config["hw_server_url"])}
check_cancel
targets -set -filter {{name =~ "Cortex-A53 #0"}}
{startup}
set ready 0
for {{set i 0}} {{$i < 100}} {{incr i}} {{
    after 50
    set mb [bridge_mrd -value 0x10000000 11]
    if {{[lindex $mb 0] == {MAGIC}}} {{
        if {{[lindex $mb 2] == 4}} {{error "Firmware initialization error [lindex $mb 8]"}}
        if {{[lindex $mb 1] == 1 && ([lindex $mb 2] == 1 || [lindex $mb 2] == 3)}} {{set ready 1; break}}
    }}
}}
if {{!$ready}} {{ error "ARM mailbox not ready; initialize the board with the matching bitstream/FSBL" }}
check_cancel
emit stage "Uploading image LLRs via JTAG (excluded from FPGA timing)"
stop
dow -data {literal(directory / "input_llr.f32")} 0x10200000
con
set seq [lindex [bridge_mrd -value 0x10000000 5] 3]
foreach limit {{{" ".join(str(int(v)) for v in limits)}}} {{
    check_cancel
    incr seq
    emit stage "FPGA decoding: iteration limit $limit"
    bridge_mwr 0x10000044 0
    bridge_mwr 0x10000014 {frames}
    bridge_mwr 0x10000018 $limit
    bridge_mwr 0x1000000C $seq
    set deadline [expr {{[clock milliseconds] + 120000}}]
    while {{1}} {{
        after 100
        if {{[file exists {literal(directory / "cancel.flag")}]}} {{bridge_mwr 0x10000044 1}}
        set mb [bridge_mrd -value 0x10000000 41]
        set state [lindex $mb 2]
        if {{[lindex $mb 4] == $seq && $state >= 3}} {{break}}
        emit progress "$limit [lindex $mb 7] {frames}"
        if {{[clock milliseconds] > $deadline}} {{bridge_mwr 0x10000044 1; error "FPGA timeout"}}
    }}
    if {{$state == 5}} {{error "CANCELLED"}}
    if {{$state != 3 || [lindex $mb 7] != {frames} || [lindex $mb 8] != 0}} {{
        error "FPGA run failed: state=$state error=[lindex $mb 8] frames=[lindex $mb 7]"
    }}
    set f [open [format {literal(str(directory / "report_%d_%d.txt"))} $limit $seq] w]
    puts $f $mb
    close $f
    emit stage "Reading FPGA output via JTAG: iteration limit $limit"
    bridge_mrd -bin -file [format {literal(str(directory / "decoded_%d_%d.u8"))} $limit $seq] 0x11200000 {frames * 384 // 4}
    emit result "$limit $seq"
}}
disconnect
}} reason]}} {{
    puts stderr "UI_ERROR: $reason"
    catch {{bridge_mwr 0x10000044 1}}
    catch {{disconnect}}
    exit 1
}}
exit 0
'''
    script = directory / "run_fpga.tcl"
    script.write_text("fconfigure stdout -encoding utf-8\nfconfigure stderr -encoding utf-8\n" + script_text, encoding="ascii", errors="backslashreplace")
    seen = []
    def relay(kind, message):
        if kind == "result":
            limit, seq = map(int, message.split())
            report = read_report(directory / f"report_{limit}_{seq}.txt")
            seen.append(limit)
            event("result", (limit, directory / f"decoded_{limit}_{seq}.u8", report))
        else:
            event(kind, message)
    begin = time.perf_counter()
    _process(script, directory, relay, cancel)
    if seen != list(limits):
        raise RuntimeError("Incomplete FPGA results")
    return time.perf_counter() - begin

def read_report(path):
    words = [int(x) for x in Path(path).read_text().split()]
    if len(words) != 41 or words[0] != MAGIC or words[1] != 1 or words[2] != 3:
        raise ValueError("Invalid firmware report")
    frequency = words[9] + (words[10] << 32)
    ticks = words[11] + (words[12] << 32)
    if frequency <= 0 or words[8] or words[7] != words[5]:
        raise ValueError("Unsuccessful firmware report")
    return {
        "frames": words[5], "iteration_limit": words[6],
        "fpga_dma_ms": ticks * 1000.0 / frequency,
        "timer_ticks": ticks, "timer_hz": frequency,
        "max_actual_iterations": words[15],
        "mean_actual_iterations": words[16] / words[5],
        "actual_iteration_histogram": {str(i): words[20+i] for i in range(21) if words[20+i]},
        "output_bytes": words[18], "dma_input_bytes": words[19],
        "dma_output_bytes": words[19],
        "source": "physical FPGA via AXI DMA; JTAG transport excluded",
    }
