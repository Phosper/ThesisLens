"""Build the two submission PDFs from editable Markdown and recorded acceptance.

Requires reportlab and the Microsoft YaHei fonts shipped with Windows.
Runtime application use does not require reportlab.
"""
import html
import json
import re
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

ROOT=Path(__file__).resolve().parent.parent
HERE=ROOT/'参赛交付'
OUT=ROOT/'output/pdf'
WIDTH,HEIGHT=A4
GREEN=HexColor('#174b43');INK=HexColor('#213b42');MUTED=HexColor('#607772')
BG=HexColor('#f7f7f2');ACCENT=HexColor('#d4bc7d')

def safe_markup(text):
    text=html.escape(text)
    return re.sub(r'https://github.com/Phosper/ThesisLens',lambda m:f'<link href="{m[0]}" color="#174b43">{m[0]}</link>',text)

def cover(c):
    c.setFillColor(GREEN);c.rect(0,0,WIDTH,HEIGHT,fill=1,stroke=0)
    c.setFillColor(ACCENT);c.rect(48,HEIGHT-95,48,4,fill=1,stroke=0)
    c.setFillColor(HexColor('#e3ece5'));c.setFont('YaHei',10)
    c.drawString(48,HEIGHT-123,'2026北京市大学生金融人工智能竞赛')
    c.drawString(48,HEIGHT-145,'第六赛道 / 买方投资备忘录编制')
    c.setFillColor(HexColor('#ffffff'));c.setFont('YaHeiBold',60)
    c.drawString(45,HEIGHT-280,'知衡')
    c.setFont('YaHeiBold',22);c.drawString(48,HEIGHT-333,'融合证据链与反向验证的')
    c.drawString(48,HEIGHT-365,'买方投研智能体')
    c.setFont('YaHei',15);c.setFillColor(ACCENT)
    c.drawString(48,HEIGHT-411,'以证据立论，以反证校准。')
    c.setStrokeColor(HexColor('#5c7d71'));c.line(48,235,WIDTH-48,235)
    c.setFillColor(HexColor('#edf2ec'));c.setFont('YaHei',11)
    for y,text in [(206,'团队名称：待填写'),(181,'学校：待填写'),(156,'队员及指导教师：待填写')]:c.drawString(48,y,text)
    c.setFont('YaHei',9);c.drawString(48,94,'项目计划书 / 可运行原型 V0.4 / 2026年10月7日')
    c.drawString(48,73,'项目代码：github.com/Phosper/ThesisLens')
    c.linkURL('https://github.com/Phosper/ThesisLens',(48,66,350,87),relative=0)
    c.showPage()

def body_page(c,text,page,total,manual=False):
    c.setFillColor(BG);c.rect(0,0,WIDTH,HEIGHT,fill=1,stroke=0)
    c.setFillColor(GREEN);c.setFont('YaHeiBold',10);c.drawString(45,HEIGHT-33,'知衡 / THESISLENS')
    c.setFillColor(MUTED);c.setFont('YaHei',9);c.drawRightString(WIDTH-45,HEIGHT-33,'演示与答辩手册' if manual else '第六赛道 / 项目计划书')
    c.setStrokeColor(HexColor('#d9e0d9'));c.line(45,HEIGHT-45,WIDTH-45,HEIGHT-45)
    y=HEIGHT-70
    styles={
        'title':ParagraphStyle('title',fontName='YaHeiBold',fontSize=21,leading=30,textColor=GREEN,wordWrap='CJK'),
        'head':ParagraphStyle('head',fontName='YaHeiBold',fontSize=12.5,leading=20,textColor=GREEN,wordWrap='CJK'),
        'body':ParagraphStyle('body',fontName='YaHei',fontSize=10.4,leading=18,textColor=INK,wordWrap='CJK'),
        'bullet':ParagraphStyle('bullet',fontName='YaHei',fontSize=10.2,leading=17.5,textColor=INK,leftIndent=10,firstLineIndent=-8,wordWrap='CJK')}
    for block in re.split(r'\n\s*\n',text.strip()):
        if not block:continue
        if block.startswith('# '):kind='title';lines=[block[2:]];after=15
        elif block.startswith('## '):kind='head';lines=[block[3:]];after=7
        elif block.startswith('- ') or re.match(r'\d+\. ',block):kind='bullet';lines=block.splitlines();after=9
        else:kind='body';lines=[block.replace('\n',' ')];after=11
        for line in lines:
            if kind=='bullet' and not re.match(r'^\d+\. ',line):line='• '+re.sub(r'^- ', '',line)
            p=Paragraph(safe_markup(line),styles[kind]);_,h=p.wrap(WIDTH-90,HEIGHT)
            if y-h<68:raise ValueError(f'Page {page}: content overflow near {line[:50]}')
            p.drawOn(c,45,y-h);y-=h+(5 if kind=='bullet' else 0)
        y-=after
    c.setStrokeColor(HexColor('#d9e0d9'));c.line(45,51,WIDTH-45,51)
    c.setFont('YaHei',8);c.setFillColor(MUTED);c.drawString(45,34,'V0.4 / 公开资料研究原型 / 封面身份信息待团队补齐')
    c.drawRightString(WIDTH-45,34,f'{page:02d} / {total:02d}')
    c.showPage()

def build():
    pdfmetrics.registerFont(TTFont('YaHei','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('YaHeiBold','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
    OUT.mkdir(parents=True,exist_ok=True)
    for source,name,count,manual in [('项目计划书.md','知衡_项目计划书.pdf',8,False),('演示与答辩手册.md','知衡_演示与答辩手册.pdf',6,True)]:
        text=(HERE/source).read_text('utf-8')
        if '{{' in text:raise ValueError('Acceptance placeholders must be materialized first')
        pages=text.split('<!-- PAGE -->');assert len(pages)==count
        file=OUT/name;c=canvas.Canvas(str(file),pagesize=A4,pageCompression=1)
        c.setTitle(name.removesuffix('.pdf'));c.setAuthor('知衡项目组（身份待填写）')
        for i,page in enumerate(pages,1):
            if i==1 and not manual:cover(c)
            else:body_page(c,page,i,count,manual)
        c.save();print(json.dumps({'file':str(file.relative_to(ROOT)),'pages':count,'bytes':file.stat().st_size},ensure_ascii=False))

if __name__=='__main__':build()
