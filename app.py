"""SignalDesk: local, read-only signal and image dataset explorer."""
import os
import sys
import json
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import pandas as pd
from PIL import Image, ImageTk, ImageOps
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.widgets import SpanSelector
from readers import read_signal, time_axis, minmax_envelope, case_annotation, read_text_preview, IMAGE_EXT

BASE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.config')))/'SignalDesk'
CASE = BASE/'examples'
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

class Viewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('SignalDesk · 数据集查看器')
        self.geometry('1440x900')
        self.minsize(1080, 700)
        try:self.state('zoomed')
        except tk.TclError:pass
        self.configure(bg='#edf2f7')
        if (BASE/'app.ico').exists(): self.iconbitmap(str(BASE/'app.ico'))
        self.data = None
        self.ann = None
        self.current = None
        self.root_path = None
        self.photo = None
        self.original_image = None
        self.image_zoom = None
        self.jobs = queue.Queue()
        self.request_id = 0
        self.busy = False
        self.selectors = []
        self.pathmap = {}
        self.status = tk.StringVar(value='选择一个数据集文件夹，或打开单个文件。所有数据仅在本机读取。')
        self._style()
        self._ui()
        self.bind('<Control-o>', lambda e:self.choose_folder())
        self.bind('<Control-O>', lambda e:self.choose_folder())
        self.bind('<Control-Shift-O>', lambda e:self.choose_file())
        self.after(100, self._poll)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(200, self.restore)

    def _style(self):
        st = ttk.Style(self)
        st.theme_use('clam')
        st.configure('.', font=('Microsoft YaHei UI', 10))
        st.configure('TFrame', background='#edf2f7')
        st.configure('TLabel', background='#edf2f7', foreground='#26374c')
        st.configure('TButton', padding=(10,6), background='#ffffff')
        st.configure('Accent.TButton', background='#126b83', foreground='white')
        st.map('Accent.TButton', background=[('active','#178da4')])
        st.configure('Treeview', rowheight=27, background='white', fieldbackground='white')
        st.configure('TNotebook.Tab', padding=(17,8))
        st.configure('TLabelframe.Label', foreground='#126b83')

    def _ui(self):
        head = tk.Frame(self, bg='#172b43', height=76)
        head.pack(fill='x')
        tk.Label(head,text='SignalDesk',font=('Segoe UI',22,'bold'),fg='white',bg='#172b43').pack(side='left',padx=20,pady=12)
        tk.Label(head,text='波形 / 图片 / 数据探索',font=('Microsoft YaHei UI',11),fg='#b6cadd',bg='#172b43').pack(side='left')
        for label,cmd in [('使用说明',self.help),('打开 CASE',self.open_case),('打开文件',self.choose_file),('选择数据集文件夹',self.choose_folder)]:
            ttk.Button(head,text=label,command=cmd).pack(side='right',padx=5,pady=16)
        self.location=ttk.Label(self,text='尚未选择数据集',padding=(16,8))
        self.location.pack(fill='x')
        panes=ttk.Panedwindow(self,orient='horizontal'); panes.pack(fill='both',expand=True,padx=12)
        left=ttk.Frame(panes,width=260); panes.add(left,weight=0)
        ttk.Label(left,text='文件浏览',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=6)
        search=ttk.Frame(left); search.pack(fill='x')
        self.query=tk.StringVar(); entry=ttk.Entry(search,textvariable=self.query);entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda e:self.search())
        ttk.Button(search,text='查找',command=self.search).pack(side='right')
        self.files=ttk.Treeview(left,show='tree',selectmode='browse')
        self.files.pack(fill='both',expand=True,pady=8)
        self.files.bind('<<TreeviewOpen>>',self.expand_folder)
        self.files.bind('<Double-1>',self.open_tree)
        self.files.bind('<Return>',self.open_tree)
        ttk.Button(left,text='刷新目录',command=lambda:self.set_root(self.root_path) if self.root_path else None).pack(fill='x')
        ttk.Label(left,text='双击文件打开 · 文件夹按需展开\n支持常见图片、CSV、NPY、MAT 等',padding=(0,8)).pack(anchor='w')
        right=ttk.Frame(panes);panes.add(right,weight=1)
        self.tabs=ttk.Notebook(right);self.tabs.pack(fill='both',expand=True)
        self.wave_tab=ttk.Frame(self.tabs);self.image_tab=ttk.Frame(self.tabs);self.table_tab=ttk.Frame(self.tabs);self.info_tab=ttk.Frame(self.tabs)
        for frame,title in [(self.wave_tab,'波形与标签'),(self.image_tab,'图片浏览'),(self.table_tab,'数据表 / 统计'),(self.info_tab,'文件信息')]: self.tabs.add(frame,text=title)
        self._wave_ui();self._image_ui()
        self.table=ttk.Treeview(self.table_tab,show='headings')
        sy=ttk.Scrollbar(self.table_tab,orient='vertical',command=self.table.yview);sx=ttk.Scrollbar(self.table_tab,orient='horizontal',command=self.table.xview)
        self.table.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        sy.pack(side='right',fill='y');sx.pack(side='bottom',fill='x');self.table.pack(fill='both',expand=True)
        self.info=tk.Text(self.info_tab,wrap='word',font=('Consolas',11),bg='white',fg='#26374c',padx=16,pady=12)
        self.info.pack(fill='both',expand=True)
        bottom=ttk.Frame(self);bottom.pack(fill='x',padx=12,pady=8)
        self.progress=ttk.Progressbar(bottom,mode='indeterminate',length=100);self.progress.pack(side='right')
        ttk.Label(bottom,textvariable=self.status).pack(side='left',fill='x',expand=True)

    def _wave_ui(self):
        bar=ttk.Frame(self.wave_tab);bar.pack(fill='x',padx=8,pady=6)
        self.offset=tk.StringVar(value='0');self.limit=tk.StringVar(value='200000')
        self.key=tk.StringVar();self.header=tk.StringVar(value='自动');self.sep=tk.StringVar(value='自动');self.orientation=tk.StringVar(value='自动')
        for label,var,width in [('起始行',self.offset,8),('每页行数',self.limit,9)]:
            ttk.Label(bar,text=label).pack(side='left',padx=3);ttk.Entry(bar,textvariable=var,width=width).pack(side='left')
        ttk.Button(bar,text='上一页',command=lambda:self.page(-1)).pack(side='left',padx=3)
        ttk.Button(bar,text='下一页',command=lambda:self.page(1)).pack(side='left')
        ttk.Button(bar,text='重新读取',command=self.reload).pack(side='left',padx=3)
        self.arraybox=ttk.Combobox(bar,textvariable=self.key,width=16,state='readonly');self.arraybox.pack(side='right');self.arraybox.bind('<<ComboboxSelected>>',lambda e:self.reload())
        ttk.Label(bar,text='数组变量').pack(side='right',padx=3)
        bar2=ttk.Frame(self.wave_tab);bar2.pack(fill='x',padx=8,pady=2)
        for label,var,values in [('表头',self.header,['自动','有表头','无表头']),('分隔符',self.sep,['自动',',',';','Tab','空格']),('数组方向',self.orientation,['自动','行=样本','列=样本'])]:
            ttk.Label(bar2,text=label).pack(side='left',padx=3);ttk.Combobox(bar2,textvariable=var,values=values,state='readonly',width=9).pack(side='left')
        self.timecol=tk.StringVar(value='按采样率生成');self.unit=tk.StringVar(value='s');self.fs=tk.StringVar(value='1')
        ttk.Label(bar2,text='时间列').pack(side='left',padx=3)
        self.timebox=ttk.Combobox(bar2,textvariable=self.timecol,width=14,state='readonly');self.timebox.pack(side='left')
        ttk.Combobox(bar2,textvariable=self.unit,values=['s','ms','us'],width=4,state='readonly').pack(side='left',padx=2)
        ttk.Label(bar2,text='采样率 Hz').pack(side='left',padx=3);ttk.Entry(bar2,textvariable=self.fs,width=7).pack(side='left')
        body=ttk.Frame(self.wave_tab);body.pack(fill='both',expand=True)
        side=ttk.Frame(body,width=145);side.pack(side='left',fill='y',padx=8,pady=8)
        ttk.Label(side,text='选择通道（可多选）').pack(anchor='w')
        self.channels=tk.Listbox(side,selectmode='extended',exportselection=False,width=18,height=6,font=('Consolas',10),selectbackground='#126b83')
        self.channels.pack(fill='y',expand=True,pady=5)
        self.normal=tk.BooleanVar();self.labels=tk.BooleanVar(value=True)
        ttk.Checkbutton(side,text='标准化显示',variable=self.normal).pack(anchor='w')
        ttk.Checkbutton(side,text='显示 CASE 标签',variable=self.labels).pack(anchor='w')
        ttk.Label(side,text='区间 / 秒').pack(anchor='w',pady=(10,0))
        self.start=tk.StringVar();self.end=tk.StringVar()
        ttk.Entry(side,textvariable=self.start,width=15).pack(fill='x',pady=2);ttk.Entry(side,textvariable=self.end,width=15).pack(fill='x',pady=2)
        ttk.Button(side,text='绘制所选通道',style='Accent.TButton',command=self.draw).pack(fill='x',pady=5)
        ttk.Button(side,text='显示本页全段',command=self.full_range).pack(fill='x',pady=2)
        ttk.Button(side,text='区间统计',command=self.stats).pack(fill='x',pady=2)
        ttk.Button(side,text='导出区间 CSV',command=self.export).pack(fill='x',pady=2)
        ttk.Button(side,text='保存波形 PNG',command=self.save_plot).pack(fill='x',pady=2)
        plot=ttk.Frame(body);plot.pack(side='left',fill='both',expand=True)
        self.fig=Figure(figsize=(10,6),dpi=100,facecolor='white')
        self.canvas=FigureCanvasTkAgg(self.fig,master=plot)
        self.toolbar=NavigationToolbar2Tk(self.canvas,plot,pack_toolbar=False);self.toolbar.pack(side='bottom',fill='x')
        self.canvas.get_tk_widget().pack(fill='both',expand=True)
        ax=self.fig.add_subplot();ax.text(.5,.5,'选择一个波形文件开始浏览\n\nCASE 可自动配对情绪标签',ha='center',va='center',transform=ax.transAxes,color='#70859b',fontsize=15);ax.set_axis_off()
        self.canvas.draw()

    def _image_ui(self):
        bar=ttk.Frame(self.image_tab);bar.pack(fill='x',padx=8,pady=8)
        for label,cmd in [('上一张',lambda:self.image_next(-1)),('下一张',lambda:self.image_next(1)),('适应窗口',lambda:self.set_zoom(None)),('原始大小',lambda:self.set_zoom(1)),('放大',lambda:self.zoom_by(1.25)),('缩小',lambda:self.zoom_by(.8))]:
            ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=3)
        self.image_info=ttk.Label(bar,text='');self.image_info.pack(side='left',padx=12)
        frame=ttk.Frame(self.image_tab);frame.pack(fill='both',expand=True)
        self.image_canvas=tk.Canvas(frame,bg='#202c3c',highlightthickness=0)
        ys=ttk.Scrollbar(frame,orient='vertical',command=self.image_canvas.yview);xs=ttk.Scrollbar(frame,orient='horizontal',command=self.image_canvas.xview)
        self.image_canvas.configure(xscrollcommand=xs.set,yscrollcommand=ys.set)
        ys.pack(side='right',fill='y');xs.pack(side='bottom',fill='x');self.image_canvas.pack(fill='both',expand=True)
        self.image_canvas.bind('<Configure>',lambda e:self.render_image() if self.original_image and self.image_zoom is None else None)
        self.image_canvas.bind('<MouseWheel>',lambda e:self.zoom_by(1.2 if e.delta>0 else 1/1.2))
        self.image_canvas.bind('<ButtonPress-1>',lambda e:self.image_canvas.scan_mark(e.x,e.y));self.image_canvas.bind('<B1-Motion>',lambda e:self.image_canvas.scan_dragto(e.x,e.y,gain=1))

    def choose_folder(self):
        p=filedialog.askdirectory(title='选择数据集文件夹',initialdir=str(self.root_path or 'F:/'))
        if p:self.set_root(Path(p))
    def choose_file(self):
        p=filedialog.askopenfilename(title='选择波形、图片或说明文件',initialdir=str(self.root_path or 'F:/'),filetypes=[('数据文件','*.csv *.tsv *.txt *.npy *.npz *.mat *.h5 *.hdf5 *.wav *.png *.jpg *.jpeg *.bmp *.tif *.webp'),('全部文件','*.*')])
        if p:self.open_file(Path(p))
    def set_root(self,path):
        path=Path(path)
        if not path.is_dir():return
        self.root_path=path;self.location.configure(text=str(path));self.query.set('')
        self.files.delete(*self.files.get_children());self.pathmap={}
        self._children('',path)
    def _children(self,parent,path):
        try:entries=sorted(path.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
        except OSError as e:self.status.set(str(e));return
        for p in entries[:3000]:
            if p.name in {'.venv','.git','__pycache__'}:continue
            iid=self.files.insert(parent,'end',text=('📁 ' if p.is_dir() else '   ')+p.name)
            self.pathmap[iid]=p
            if p.is_dir():self.files.insert(iid,'end',text='…')
    def expand_folder(self,event=None):
        iid=self.files.focus();p=self.pathmap.get(iid)
        if p and p.is_dir():
            children=self.files.get_children(iid)
            if children and children[0] not in self.pathmap:
                self.files.delete(*children);self._children(iid,p)
    def open_tree(self,event=None):
        p=self.pathmap.get(self.files.focus())
        if p and p.is_file():self.open_file(p)
    def search(self):
        if not self.root_path:return
        term=self.query.get().strip().lower()
        if not term:return self.set_root(self.root_path)
        root=self.root_path
        def work():
            result=[]
            for folder,dirs,files in os.walk(root):
                dirs[:]=[d for d in dirs if d not in {'.venv','.git','__pycache__'}]
                for name in files:
                    if term in name.lower():result.append(Path(folder)/name)
                    if len(result)>=2000:return result
            return result
        def done(paths):
            self.files.delete(*self.files.get_children());self.pathmap={}
            for p in paths:
                iid=self.files.insert('','end',text=str(p.relative_to(root)));self.pathmap[iid]=p
            self.status.set(f'找到 {len(paths)} 个文件（最多显示 2000 项）。')
        self.run_job(work,done,'正在查找文件…')
    def run_job(self,work,done,message):
        self.request_id+=1;rid=self.request_id;self.busy=True;self.progress.start(12);self.status.set(message)
        def task():
            try:self.jobs.put((rid,done,work(),None))
            except Exception as e:self.jobs.put((rid,done,None,e))
        threading.Thread(target=task,daemon=True).start()
    def _poll(self):
        try:
            while True:
                rid,done,result,error=self.jobs.get_nowait()
                if rid!=self.request_id:continue
                self.busy=False;self.progress.stop()
                if error:
                    self.status.set('读取失败：'+str(error));messagebox.showerror('无法读取',str(error))
                else:
                    try:done(result)
                    except Exception as e:
                        self.status.set('显示失败：'+str(e));messagebox.showerror('显示失败',str(e))
        except queue.Empty:pass
        self.after(100,self._poll)
    def open_file(self,path,reset=True):
        path=Path(path)
        if not path.is_file():return
        if reset:self.offset.set('0');self.key.set('')
        self.current=path;self.location.configure(text=str(path))
        ext=path.suffix.lower()
        if ext in IMAGE_EXT:
            def load():
                with Image.open(path) as im:return ImageOps.exif_transpose(im).convert('RGB').copy()
            def show(im):
                self.original_image=im;self.image_path=path;self.image_zoom=None;self.tabs.select(self.image_tab);self.after(50,self.render_image)
                self.status.set(f'图片：{path.name} · {im.width} × {im.height}');self.set_info(f'{path}\n尺寸：{im.width} × {im.height}\n大小：{path.stat().st_size:,} 字节\n仅显示第一帧（如为动画或多页 TIFF）。')
            self.run_job(load,show,'正在读取图片…');return
        if ext not in {'.csv','.tsv','.npy','.npz','.mat','.h5','.hdf5','.wav'} and (ext!='.txt' or 'readme' in path.name.lower()):
            def show(text):self.set_info(text);self.tabs.select(self.info_tab);self.status.set('文件预览：'+path.name)
            self.run_job(lambda:read_text_preview(path),show,'读取文件信息…');return
        try:offset=int(self.offset.get());limit=int(self.limit.get())
        except ValueError:return messagebox.showerror('参数错误','起始行和每页行数必须是整数。')
        key,header,sep,orient=self.key.get(),self.header.get(),self.sep.get(),self.orientation.get()
        def load():
            data=read_signal(path,offset,limit,key,header,sep,orient)
            annpath=case_annotation(path)
            ann=read_signal(annpath,limit=2000000) if annpath else None
            return data,ann
        self.run_job(load,self.show_signal,'正在读取波形（大文件按页载入）…')
    def reload(self):
        if self.current:self.open_file(self.current,False)
    def page(self,direction):
        if not self.data:return
        if direction>0 and not self.data.has_more:return self.status.set('已经是最后一页。')
        try:self.offset.set(str(max(0,int(self.offset.get())+direction*int(self.limit.get()))));self.reload()
        except ValueError:messagebox.showerror('参数错误','请输入整数行数。')
    def show_signal(self,pair):
        self.data,self.ann=pair;d=self.data
        self.channels.delete(0,'end')
        nums=d.numeric
        for c in nums:self.channels.insert('end',c)
        defaults=[c for c in ['ecg','bvp','rsp'] if c in nums] or [c for c in nums if c!=d.time_column][:3]
        for c in defaults:self.channels.selection_set(nums.index(c))
        self.timebox.configure(values=['按采样率生成']+nums);self.timecol.set(d.time_column or '按采样率生成');self.unit.set(d.time_unit)
        if d.sample_rate:self.fs.set(str(d.sample_rate))
        self.arraybox.configure(values=d.arrays)
        if d.arrays and self.key.get() not in d.arrays:self.key.set(d.arrays[0])
        self.start.set('');self.end.set('');self.tabs.select(self.wave_tab)
        self.show_table(d.frame.head(500))
        self.set_info(f'{d.path}\n\n读取行：{d.offset:,} 至 {d.offset+len(d.frame)-1:,}\n当前页 {len(d.frame):,} 行 / {len(d.frame.columns)} 列\n后续数据：{"还有下一页" if d.has_more else "文件末尾"}\n\n'+ '\n'.join(d.notes)+ ('\n\nCASE 同步标签：'+str(self.ann.path) if self.ann else '')+'\n\n列类型：\n'+str(d.frame.dtypes))
        self.draw()
    def selected(self):return [self.channels.get(i) for i in self.channels.curselection()]
    def window_data(self):
        if self.data is None:raise ValueError('请先打开波形文件。')
        x=time_axis(self.data,self.timecol.get(),self.unit.get(),float(self.fs.get()))
        valid=np.isfinite(x)
        if not valid.any():raise ValueError('时间轴没有有效数值。')
        lo=float(self.start.get()) if self.start.get().strip() else float(np.min(x[valid]))
        hi=float(self.end.get()) if self.end.get().strip() else float(np.max(x[valid]))
        if lo>=hi:raise ValueError('区间起点必须小于终点。')
        mask=valid&(x>=lo)&(x<=hi)
        if not mask.any():raise ValueError('所选区间不在当前分页内；请切换分页。')
        return x,mask,lo,hi
    def draw(self):
        if self.data is None:return
        try:
            x,mask,lo,hi=self.window_data();cols=self.selected()
            if not cols:raise ValueError('请在左侧选择至少一个数值通道。')
            if len(cols)>8:raise ValueError('一次最多绘制 8 个通道，便于查看。')
            ann=self.ann if self.labels.get() else None
            n=len(cols)+(1 if ann else 0)
            for s in self.selectors:s.disconnect_events()
            self.selectors=[];self.fig.clear();axes=self.fig.subplots(n,1,sharex=True,squeeze=False).ravel()
            colors=['#117c91','#dd773e','#7457b7','#3e965a']
            for i,c in enumerate(cols):
                y=self.data.frame[c].to_numpy(dtype=float)[mask]
                if self.normal.get():
                    sd=np.nanstd(y);y=(y-np.nanmean(y))/(sd if sd>0 else 1)
                px,py=minmax_envelope(x[mask],y)
                axes[i].plot(px,py,lw=.8,color=colors[i%4]);axes[i].set_ylabel(c);axes[i].grid(alpha=.18)
            if ann:
                tx=time_axis(ann,ann.time_column,ann.time_unit);am=np.isfinite(tx)&(tx>=lo)&(tx<=hi)
                for c,color in [('valence','#aa4f86'),('arousal','#d59a24')]:
                    if c in ann.frame:axes[-1].plot(tx[am],ann.frame[c].to_numpy()[am],label=c,color=color,lw=1.2)
                axes[-1].set_ylabel('情绪标签');axes[-1].set_ylim(.5,9.5);axes[-1].legend(loc='upper right',fontsize=8);axes[-1].grid(alpha=.18)
            axes[-1].set_xlabel('时间 / 秒');axes[0].set_xlim(lo,hi)
            axes[0].set_title(f'{self.data.path.name}  ·  {int(mask.sum()):,} 个样本',loc='left',fontsize=11,pad=8)
            self.fig.subplots_adjust(left=.10,right=.98,top=.93,bottom=.10,hspace=.22)
            self.selectors=[SpanSelector(ax,self.on_span,'horizontal',useblit=True,props=dict(alpha=.16,facecolor='#126b83'),button=1) for ax in axes]
            self.canvas.draw();self.toolbar.update()
            self.status.set(f'{self.data.path.name} | 本页 {len(self.data.frame):,} 行 | {lo:.3f}–{hi:.3f} 秒 | 拖选区间；下方工具栏可缩放和平移'+(' | 无时间列：请确认采样率' if not self.data.time_column else ''))
        except Exception as e:messagebox.showerror('无法绘图',str(e))
    def on_span(self,lo,hi):
        if self.toolbar.mode or hi-lo<1e-10:return
        self.start.set(f'{lo:.6f}');self.end.set(f'{hi:.6f}');self.status.set(f'已选 {lo:.3f}–{hi:.3f} 秒，点击“绘制所选通道”放大，或导出区间。')
    def full_range(self):self.start.set('');self.end.set('');self.draw()
    def show_table(self,frame):
        self.table.delete(*self.table.get_children());columns=[str(c) for c in frame.columns];self.table.configure(columns=columns)
        for c in columns:self.table.heading(c,text=c);self.table.column(c,width=120,minwidth=60,stretch=False)
        for row in frame.itertuples(index=False,name=None):self.table.insert('','end',values=[f'{v:.6g}' if isinstance(v,float) else str(v) for v in row])
    def stats(self):
        try:
            x,mask,lo,hi=self.window_data();cols=self.selected()
            frame=self.data.frame.loc[mask,cols];summary=frame.describe().T;summary['missing']=frame.isna().sum();summary.insert(0,'channel',summary.index)
            self.show_table(summary);self.tabs.select(self.table_tab);self.status.set(f'原始值统计（不受标准化显示影响）：{lo:.3f}–{hi:.3f} 秒')
        except Exception as e:messagebox.showerror('无法统计',str(e))
    def export(self):
        try:
            x,mask,lo,hi=self.window_data();cols=self.selected()
            if not cols:raise ValueError('请选择通道。')
            frame=self.data.frame.loc[mask,cols].copy();frame.insert(0,'viewer_time_seconds',x[mask])
            p=filedialog.asksaveasfilename(title='导出所选区间（原始值）',defaultextension='.csv',initialfile=f'{self.data.path.stem}_segment.csv',filetypes=[('CSV','*.csv')])
            if p:
                if Path(p).resolve()==self.data.path.resolve():raise ValueError('请使用新文件名，不覆盖原始数据。')
                frame.to_csv(p,index=False,encoding='utf-8-sig');self.status.set(f'已导出 {len(frame):,} 行：{p}')
        except Exception as e:messagebox.showerror('导出失败',str(e))
    def save_plot(self):
        p=filedialog.asksaveasfilename(defaultextension='.png',filetypes=[('PNG','*.png')],initialfile='waveform.png')
        if p:self.fig.savefig(p,dpi=180);self.status.set('已保存波形图：'+p)
    def set_info(self,text):self.info.configure(state='normal');self.info.delete('1.0','end');self.info.insert('1.0',text);self.info.configure(state='disabled')
    def set_zoom(self,z):self.image_zoom=z;self.render_image()
    def zoom_by(self,factor):
        if self.original_image:self.image_zoom=min(8,max(.02,(self.image_zoom or self.fit_zoom())*factor));self.render_image()
    def fit_zoom(self):
        if not self.original_image:return 1
        return min(max(1,self.image_canvas.winfo_width()-20)/self.original_image.width,max(1,self.image_canvas.winfo_height()-20)/self.original_image.height,1.)
    def render_image(self):
        if not self.original_image:return
        zoom=self.fit_zoom() if self.image_zoom is None else self.image_zoom
        w,h=max(1,int(self.original_image.width*zoom)),max(1,int(self.original_image.height*zoom))
        if w*h>50000000:return self.status.set('缩放尺寸过大，请缩小。')
        im=self.original_image.resize((w,h),Image.Resampling.LANCZOS);self.photo=ImageTk.PhotoImage(im)
        self.image_canvas.delete('all');cw,ch=self.image_canvas.winfo_width(),self.image_canvas.winfo_height()
        self.image_canvas.create_image(max(cw,w)//2,max(ch,h)//2,image=self.photo,anchor='center');self.image_canvas.configure(scrollregion=(0,0,max(cw,w),max(ch,h)))
        self.image_info.configure(text=f'{self.original_image.width} × {self.original_image.height}   {zoom:.0%}')
    def image_next(self,step):
        if not hasattr(self,'image_path'):return
        files=sorted([p for p in self.image_path.parent.iterdir() if p.suffix.lower() in IMAGE_EXT],key=lambda p:p.name.lower())
        if files:self.open_file(files[(files.index(self.image_path)+step)%len(files)])
    def open_case(self):
        folder=filedialog.askdirectory(title='选择已解压的 CASE_full 文件夹')
        if not folder:return
        root=Path(folder)
        candidates=[root,root/'CASE_full']
        for candidate in candidates:
            p=candidate/'data/interpolated/physiological/sub_1.csv'
            if p.exists():
                self.set_root(candidate);self.open_file(p);return
        self.set_root(root)
        messagebox.showinfo('CASE','已打开文件夹。未找到标准 CASE 路径，请在左侧手动选择波形文件。')
    def restore(self):
        restored=False
        try:
            config=json.loads((CONFIG/'settings.json').read_text(encoding='utf-8'))
            path=Path(config.get('root',''))
            if path.is_dir():self.set_root(path);restored=True
        except Exception:pass
        if len(sys.argv)>1 and Path(sys.argv[1]).is_file():self.open_file(Path(sys.argv[1]))
        elif not restored:
            self.set_root(CASE)
            p=CASE/'data/interpolated/physiological/sub_1.csv'
            if p.exists():self.open_file(p)
    def help(self):
        messagebox.showinfo('使用说明','1. 选择文件夹后，双击文件打开；可按文件名搜索。\n2. 波形：多选通道，确认时间列/单位或采样率，再绘图。\n3. 大文件默认每页 20 万行，可翻页或指定起始行。\n4. 拖动波形选择区间，点击绘制放大；可导出 CSV/PNG。\n5. CASE physiological 文件自动匹配同被试 annotations。\n6. 图片支持上一张/下一张、滚轮缩放、拖动平移。\n7. 数值 MAT/NPZ/HDF5 可切换变量；不执行 pickle/PT。\n\n所有文件只读，导出使用新文件。无时间列时默认 1 Hz 只是占位，必须按数据说明修改。\n数据表最多预览 500 行；统计与导出使用当前页选中区间的完整原始值。')
    def close(self):
        try:
            CONFIG.mkdir(parents=True,exist_ok=True)
            (CONFIG/'settings.json').write_text(json.dumps({'root':str(self.root_path or CASE)},ensure_ascii=False),encoding='utf-8')
        except OSError:pass
        self.destroy()

if __name__=='__main__':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:pass
    app=Viewer()
    def report_error(typ,value,tb):
        CONFIG.mkdir(parents=True,exist_ok=True)
        with (CONFIG/'error.log').open('a',encoding='utf-8') as f:traceback.print_exception(typ,value,tb,file=f)
        messagebox.showerror('发生错误',str(value)+'\n详情已保存到 '+str(CONFIG/'error.log'))
    app.report_callback_exception=report_error
    app.mainloop()
