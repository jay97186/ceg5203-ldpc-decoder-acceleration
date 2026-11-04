# Run AFTER starting kria_cpu_baseline.elf with Vitis Run.
# Does not reset the board or program PL. Data movement excluded from timer.
targets -set -filter {name =~ "Cortex-A53 #0"}
set mb [mrd -value 0x10000000 5]
if {[lindex $mb 0]!=0x43505542 || [lindex $mb 2]!=1} {
 error "Start kria_cpu_baseline.elf with Vitis Run first (fresh CPU READY required)."
}
puts "Uploading the EXACT LLR from FPGA request_4 (outside timer)..."
stop
dow -data {C:/Users/jay/Desktop/CEG_5203/Final_Project/ldpc_fpga_terminal/runs/realterm_20261024_222234_758970/request_4/input_llr.f32} 0x10200000
con
set result_file [open {C:/Users/jay/Documents/Codex/2026-10-23/hi/outputs/kria_cpu_baseline/a53_reports.txt} w]
puts $result_file "# warmup=1 measured=5 frames=6081 limit=20"
flush $result_file
for {set seq 1} {$seq<=6} {incr seq} {
 mwr 0x10000014 6081
 mwr 0x10000018 20
 mwr 0x1000000C $seq
 set deadline [expr {[clock milliseconds]+600000}]
 while {1} {
  after 200
  set report [mrd -value 0x10000000 42]
  if {[lindex $report 4]==$seq && [lindex $report 2]>=3} {break}
  if {[clock milliseconds]>$deadline} {close $result_file;error "A53 CPU timeout; stop and inspect in Vitis"}
 }
 if {[lindex $report 2]!=3 || [lindex $report 8]!=0} {close $result_file;error "A53 request failed: $report"}
 puts $result_file $report
 flush $result_file
 set ticks [expr {[lindex $report 11]+(wide([lindex $report 12])<<32)}]
 set hz [expr {[lindex $report 9]+(wide([lindex $report 10])<<32)}]
 set ms [expr {1000.0*$ticks/$hz}]
 puts [format "A53 run %d: %.3f ms %s" $seq $ms [expr {$seq==1?"(warmup excluded)":"(measured)"}]]
}
close $result_file
mrd -bin -file {C:/Users/jay/Documents/Codex/2026-10-23/hi/outputs/kria_cpu_baseline/a53_decoded.u8} 0x11200000 583776
puts "DONE. Run Analyze_Results.cmd to validate bits and calculate speedup."
