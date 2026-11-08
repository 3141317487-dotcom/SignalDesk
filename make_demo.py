"""Generate deterministic synthetic signals; no human or licensed dataset data."""
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

def generate(root):
    root=Path(root)
    phys=root/'data/interpolated/physiological'
    ann=root/'data/interpolated/annotations'
    phys.mkdir(parents=True,exist_ok=True);ann.mkdir(parents=True,exist_ok=True)
    t=np.arange(10000)/1000
    phase=(t%0.85)/0.85
    ecg=np.exp(-((phase-.2)/.025)**2)-.2*np.exp(-((phase-.25)/.035)**2)
    pd.DataFrame({'daqtime':t*1000,'ecg':ecg,'bvp':np.sin(2*np.pi*t/0.85),'rsp':np.sin(2*np.pi*.25*t)}).to_csv(phys/'sub_1.csv',index=False)
    a=t[::50]
    pd.DataFrame({'jstime':a*1000,'valence':5+np.sin(a*.4),'arousal':5+np.cos(a*.4)}).to_csv(ann/'sub_1.csv',index=False)
    im=Image.new('RGB',(1000,500),'#172b43');draw=ImageDraw.Draw(im)
    draw.text((35,25),'SignalDesk | SYNTHETIC DEMO | NOT REAL PARTICIPANT DATA',fill='white')
    for y0,signal,color in [(150,ecg,'#2dd4bf'),(350,np.sin(2*np.pi*.25*t),'#fbbf24')]:
        points=[(30+i*940/999,y0-float(signal[i*10])*65) for i in range(1000)]
        draw.line(points,fill=color,width=3)
    im.save(root/'demo.png')

if __name__=='__main__':generate(Path(__file__).parent/'examples')
