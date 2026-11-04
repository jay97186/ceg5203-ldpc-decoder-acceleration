"""English monochrome fixed-LLR demonstration, one run per iteration budget."""
from pathlib import Path
from datetime import datetime
import argparse, os, queue, threading, tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import numpy as np
from codec import Codec,reconstruct
from demo_runner import ROOT, DATASET, cases, configure, run_case, BoardLock, parse_limits

class App(tk.Tk):
    def __init__(self,version):
        super().__init__()
        self.title('LDPC FPGA | Teacher Demonstration')
        self.geometry('1320x880');self.minsize(1000,700);self.configure(bg='white')
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('.',background='white',foreground='#111111',font=('Segoe UI',11))
        style.configure('TButton',padding=8,background='#eeeeee',foreground='black')
        self.items=cases();self.events=queue.Queue();self.cancel=threading.Event()
        self.busy=False;self.photos=[];self.folder=ROOT/'results'
        top=ttk.Frame(self,padding=16);top.pack(fill='x')
        ttk.Label(top,text='LDPC FPGA — Fixed Teammate LLR',font=('Segoe UI',21,'bold')).pack(anchor='w')
        ttk.Label(top,text='AWGN Eb/N0 = 3 dB | Original float32 LLR | No regenerated noise | Single run per iteration limit').pack(anchor='w',pady=(8,12))
        bar=ttk.Frame(top);bar.pack(fill='x')
        self.version=tk.StringVar(value=version);self.case=tk.StringVar(value=self.items[0]['id'])
        self.limits=tk.StringVar(value='1,2,5,10,20')
        ttk.Label(bar,text='Hardware').pack(side='left')
        self.vbox=ttk.Combobox(bar,textvariable=self.version,values=['v1','v2','v3'],state='readonly',width=5);self.vbox.pack(side='left',padx=8)
        ttk.Label(bar,text='Image').pack(side='left')
        self.cbox=ttk.Combobox(bar,textvariable=self.case,values=[c['id'] for c in self.items],state='readonly',width=25);self.cbox.pack(side='left',padx=8)
        ttk.Label(bar,text='Iteration limits').pack(side='left')
        self.entry=ttk.Entry(bar,textvariable=self.limits,width=18);self.entry.pack(side='left',padx=8)
        self.run=ttk.Button(bar,text='Run FPGA',command=self.start);self.run.pack(side='left',padx=8)
        ttk.Button(bar,text='Open results',command=lambda:os.startfile(self.folder)).pack(side='left',padx=8)
        self.progress=ttk.Progressbar(top,mode='indeterminate');self.progress.pack(fill='x',pady=(14,0))
        images=ttk.Frame(self,padding=12);images.pack(fill='x')
        self.labels=[]
        for i,title in enumerate(['Original','Noisy received (fixed LLR)','FPGA decoded']):
            frame=ttk.Frame(images);frame.pack(side='left',expand=True,fill='both')
            ttk.Label(frame,text=title,font=('Segoe UI',13,'bold')).pack()
            label=ttk.Label(frame,anchor='center');label.pack(pady=10);self.labels.append(label)
        columns=('limit','ms','errors','ber','iterations','reference')
        self.table=ttk.Treeview(self,columns=columns,show='headings',height=7)
        for key,title in zip(columns,['Iteration limit','FPGA + DMA (ms)','Payload errors','Payload BER','Mean iterations','Reference mismatches']):
            self.table.heading(key,text=title);self.table.column(key,width=170,anchor='center')
        self.table.pack(fill='x',padx=24,pady=8)
        ttk.Label(self,text='Timing includes ARM control, AXI DMA and PL decoding. Excludes PC preparation, JTAG transfer and image rendering.').pack(anchor='w',padx=24)
        self.status=tk.StringVar(value='Ready. Close other board controllers. This UI initializes the selected hardware automatically.')
        ttk.Label(self,textvariable=self.status,wraplength=1220).pack(fill='x',padx=24,pady=8)
        self.log=tk.Text(self,height=6,bg='#f5f5f5',fg='black',font=('Consolas',10));self.log.pack(fill='both',expand=True,padx=24,pady=(0,14))
        self.cbox.bind('<<ComboboxSelected>>',lambda _:self.preview())
        self.protocol('WM_DELETE_WINDOW',self.close);self.preview();self._poll_id=self.after(100,self.poll)
    def show_image(self,index,image):
        im=image.copy();im.thumbnail((390,290));photo=ImageTk.PhotoImage(im)
        self.labels[index].configure(image=photo)
        while len(self.photos)<=index:self.photos.append(None)
        self.photos[index]=photo
    def preview(self):
        c=next(c for c in self.items if c['id']==self.case.get())
        with Image.open(DATASET/c['image']) as im:self.show_image(0,im.convert('RGB'))
        llr=np.fromfile(DATASET/c['llr'],dtype='<f4').reshape(-1,384)
        self.show_image(1,reconstruct(Codec(),(llr<0).astype('u1'),(256,192)))
        self.labels[2].configure(image='');self.table.delete(*self.table.get_children())
    def start(self):
        try:limits=parse_limits(self.limits.get());configure(self.version.get())
        except Exception as exc:messagebox.showerror('Settings',str(exc));return
        self.busy=True;self.cancel.clear();self.run.configure(state='disabled')
        self.vbox.configure(state='disabled');self.cbox.configure(state='disabled');self.entry.configure(state='disabled')
        self.table.delete(*self.table.get_children());self.progress.start()
        version=self.version.get();case=next(c for c in self.items if c['id']==self.case.get())
        self.folder=ROOT/'results'/('ui_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))/version/case['id']
        def worker():
            try:
                with BoardLock():run_case(version,case,limits,self.folder,False,True,lambda k,m:self.events.put((k,m)),self.cancel)
                self.events.put(('done',str(self.folder)))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,msg=self.events.get_nowait()
                if kind=='sample':
                    r=msg['record']
                    with Image.open(msg['image']) as im:self.show_image(2,im)
                    ref=r.get('dataset_reference_bit_mismatches')
                    self.table.insert('','end',values=(r['iteration_limit'],f"{r['fpga_dma_ms']:.3f}",r['payload_bit_errors'],f"{r['payload_ber']:.8g}",f"{r['mean_actual_iterations']:.3f}",'N/A (reference is limit 20)' if ref is None else ref))
                elif kind in ('stage','progress'):
                    self.status.set(str(msg));self.log.insert('end',str(msg)+'\n');self.log.see('end')
                elif kind in ('done','error'):
                    self.busy=False;self.progress.stop();self.run.configure(state='normal')
                    self.vbox.configure(state='readonly');self.cbox.configure(state='readonly');self.entry.configure(state='normal')
                    self.status.set(('Saved: ' if kind=='done' else 'ERROR: ')+str(msg))
                    if kind=='error':messagebox.showerror('FPGA run',str(msg))
        except queue.Empty:pass
        self._poll_id=self.after(100,self.poll)
    def destroy(self):
        if hasattr(self,'_poll_id'):
            self.after_cancel(self._poll_id)
        super().destroy()
    def close(self):
        if self.busy:
            messagebox.showinfo('FPGA running','Wait for the current run to finish before closing.');return
        self.destroy()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--version',default='v3',choices=['v1','v2','v3']);a=p.parse_args()
    App(a.version).mainloop()
