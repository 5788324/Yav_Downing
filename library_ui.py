"""Yav 私人资料馆桌面浏览界面。"""
import os
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk


class LibraryWindow(tk.Toplevel):
    PAGE_SIZE = 60

    def __init__(self, parent, store, enrich_callback):
        super().__init__(parent)
        self.store, self.enrich_callback = store, enrich_callback
        self.images = []
        self.title("Yav · 私人影视资料馆")
        self.geometry("1180x780")
        self.minsize(880, 620)
        self.configure(bg="#f6f8fc")
        self.search_var=tk.StringVar(); self.series_var=tk.StringVar(); self.site_var=tk.StringVar()
        self.favorite_var=tk.BooleanVar(); self.magnet_var=tk.StringVar(value="全部")
        self._build(); self.refresh()

    def _build(self):
        top=ttk.Frame(self,padding=(18,14)); top.pack(fill="x")
        ttk.Label(top,text="我的影视资料馆",font=("Microsoft YaHei UI",18,"bold")).pack(side="left",padx=(0,18))
        ttk.Entry(top,textvariable=self.search_var,width=28).pack(side="left")
        ttk.Button(top,text="搜索",command=self.refresh).pack(side="left",padx=6)
        self.series_combo=ttk.Combobox(top,textvariable=self.series_var,width=16,state="readonly"); self.series_combo.pack(side="left",padx=4)
        self.series_combo.bind("<<ComboboxSelected>>",lambda _e:self.refresh())
        ttk.Combobox(top,textvariable=self.site_var,values=["","javdb","jphoo"],width=9,state="readonly").pack(side="left",padx=4)
        ttk.Checkbutton(top,text="仅收藏",variable=self.favorite_var,command=self.refresh).pack(side="left",padx=5)
        ttk.Combobox(top,textvariable=self.magnet_var,values=["全部","有磁力","暂无磁力"],width=10,state="readonly").pack(side="left",padx=4)
        ttk.Button(top,text="刷新",command=self.refresh).pack(side="left",padx=4)
        ttk.Button(top,text="补全当前系列资料与封面",command=self.enrich).pack(side="right")
        self.status=ttk.Label(self,text=""); self.status.pack(anchor="w",padx=20,pady=(0,6))

        outer=ttk.Frame(self); outer.pack(fill="both",expand=True,padx=16,pady=(0,14))
        self.canvas=tk.Canvas(outer,bg="#f6f8fc",highlightthickness=0)
        bar=ttk.Scrollbar(outer,orient="vertical",command=self.canvas.yview); self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right",fill="y"); self.canvas.pack(side="left",fill="both",expand=True)
        self.cards=ttk.Frame(self.canvas); self.card_window=self.canvas.create_window((0,0),window=self.cards,anchor="nw")
        self.cards.bind("<Configure>",lambda _e:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self.card_window,width=e.width))
        self.canvas.bind_all("<MouseWheel>",lambda e:self.canvas.yview_scroll(int(-e.delta/120),"units"))

    def refresh(self):
        self.series_combo["values"]=[""]+self.store.series_names()
        has={"全部":None,"有磁力":True,"暂无磁力":False}[self.magnet_var.get() or "全部"]
        works=self.store.query_works(self.search_var.get().strip(),self.series_var.get(),self.site_var.get(),self.favorite_var.get(),has,self.PAGE_SIZE)
        for widget in self.cards.winfo_children(): widget.destroy()
        self.images=[]
        for index,work in enumerate(works): self._card(work,index)
        stats=self.store.stats()
        self.status.config(text=f"共 {stats.get('works') or 0} 部影片 · 已缓存封面 {stats.get('covers') or 0} · 当前显示 {len(works)} 部")

    def _card(self, work, index):
        card=ttk.Frame(self.cards,padding=7,relief="solid",borderwidth=1)
        card.grid(row=index//5,column=index%5,padx=7,pady=7,sticky="nsew")
        image=self._thumbnail(work.get("cover_path"))
        button=tk.Button(card,image=image,command=lambda w=work:self.details(w["id"]),width=145,height=200,bg="#e2e8f0",relief="flat")
        button.image=image; button.pack(); self.images.append(image)
        title=(work.get("title") or "（待补全标题）")[:32]
        ttk.Button(card,text=title,command=lambda w=work:self.details(w["id"]),width=22).pack(fill="x",pady=(4,0))
        ttk.Label(card,text=f"{work.get('series','')} · {work.get('release_date','') or '日期待补'}",width=23).pack(anchor="w")
        flags=("★ " if work.get("favorite") else "") + ("有磁力" if work.get("magnet_count") else "暂无磁力")
        ttk.Label(card,text=flags).pack(anchor="w")
        self.cards.grid_columnconfigure(index%5,weight=1)

    def _thumbnail(self,path):
        try:
            if path and os.path.exists(path):
                image=Image.open(path).convert("RGB"); image.thumbnail((145,200)); canvas=Image.new("RGB",(145,200),(226,232,240)); canvas.paste(image,((145-image.width)//2,(200-image.height)//2)); return ImageTk.PhotoImage(canvas)
        except Exception: pass
        image=Image.new("RGB",(145,200),(203,213,225)); return ImageTk.PhotoImage(image)

    def enrich(self):
        series=self.series_var.get()
        if not series:
            messagebox.showwarning("请选择系列","请先从筛选框选择一个系列，再补全该系列的封面与资料。",parent=self); return
        self.enrich_callback(series, self.refresh)

    def details(self, work_id):
        work=self.store.get_work(work_id)
        if not work:return
        dlg=tk.Toplevel(self); dlg.title("影片资料"); dlg.geometry("760x600"); dlg.transient(self)
        body=ttk.Frame(dlg,padding=16); body.pack(fill="both",expand=True)
        image=self._thumbnail(work.get("cover_path")); label=tk.Label(body,image=image,bg="#e2e8f0",width=145,height=200); label.image=image; label.grid(row=0,column=0,rowspan=9,sticky="n")
        fields={"标题":work.get("title",""),"演员":", ".join(work.get("actors",[])),"系列":work.get("series","") ,"发行商":work.get("publisher","") ,"发行日期":work.get("release_date","") ,"封面网址":work.get("cover_url_manual") or work.get("cover_url_auto","")}
        entries={}
        for row,(name,value) in enumerate(fields.items()):
            ttk.Label(body,text=name).grid(row=row,column=1,sticky="e",padx=(15,6),pady=4)
            entry=ttk.Entry(body,width=64); entry.insert(0,value or ""); entry.grid(row=row,column=2,sticky="ew",pady=4); entries[name]=entry
        favorite=tk.BooleanVar(value=bool(work.get("favorite"))); ttk.Checkbutton(body,text="收藏",variable=favorite).grid(row=6,column=1,sticky="w",padx=15,pady=4)
        ttk.Label(body,text="磁力版本").grid(row=7,column=1,sticky="nw",padx=15,pady=5)
        magnets=tk.Text(body,height=9,width=62); magnets.grid(row=7,column=2,sticky="nsew")
        magnets.insert("1.0","\n".join(f"{m.get('size_gb',0):.2f} GB  {m['magnet']}" for m in work.get("magnets",[])) or "暂无磁力")
        ttk.Label(body,text="来源网页").grid(row=8,column=1,sticky="ne",padx=15,pady=5); ttk.Label(body,text=work.get("source_url",""),wraplength=450).grid(row=8,column=2,sticky="w")
        def save():
            self.store.update_manual(work_id,entries['标题'].get(),entries['演员'].get(),entries['系列'].get(),entries['发行商'].get(),entries['发行日期'].get(),entries['封面网址'].get(),favorite.get())
            self.refresh(); dlg.destroy()
        ttk.Button(body,text="保存手动修改",command=save).grid(row=9,column=2,sticky="e",pady=14)
        body.grid_columnconfigure(2,weight=1); body.grid_rowconfigure(7,weight=1)
