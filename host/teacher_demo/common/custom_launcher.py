import argparse
from demo_runner import configure,BoardLock
import app_custom
p=argparse.ArgumentParser();p.add_argument('--version',choices=['v1','v2','v3'],required=True);a=p.parse_args()
configure(a.version)
app_custom.DEMO_VERSION=a.version
with BoardLock():
 app=app_custom.App()
 app.title('LDPC '+a.version+' | Custom image / generated AWGN (not fixed teammate LLR)')
 app.mainloop()
