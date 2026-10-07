"""Encode actual CUA screenshots as an explicitly labelled, silent captioned demo.

Requires Pillow, FFmpeg, and Microsoft YaHei on Windows. Screenshots are saved
in the repository so this presentation can be rebuilt without browser control.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent.parent
SCREENS=ROOT/'知衡初版/demo/screens'
FRAMES=ROOT/'tmp/video'
OUT=ROOT/'参赛交付/知衡_项目简介.mp4'
FONT='C:/Windows/Fonts/msyh.ttc';BOLD='C:/Windows/Fonts/msyhbd.ttc'
SIZE=(1280,800)
GREEN='#174b43';LIGHT='#f5f6ef';GOLD='#d4bc7d'

SCENES=[
    (None,12,'知衡','融合证据链与反向验证的买方投研智能体'),
    ('01_workbench.jpg',18,'固定公司与研究时点，从问题出发组织证据。','第六赛道：买方投资备忘录编制 / 美的、格力、海尔'),
    ('02_depth.jpg',25,'财务解剖：合并资产负债、公式和物理原页。','半年度变动是期末对期初；不能改写为同比。'),
    ('03_regions.jpg',20,'海外收入1131.27亿元，占43.50%，同比增长5.54%。','分部、地区和股份分别回到原页，检查口径与分母。'),
    ('04_valuation.jpg',22,'TTM来自确定性桥接，8 / 12 / 16倍PE属于演示假设。','股数、库存股与稀释仍需核对；情景值不是目标价。'),
    ('05_logic.jpg',25,'T编号连接论据、风险、失效条件与持续跟踪。','展示真实模型保存记录；原稿与剩余复核问题均保留。'),
    ('06_trace.jpg',22,'规划、检索、财务计算、写作、复核和修订逐步留痕。','这次真实运行44.55秒；排序格式失败时明确降级。'),
    ('07_review.jpg',18,'人工核验登记支持依据或反证，后续阈值提示复核。','结构分100不代表事实正确；本案例仍有高风险复核事项。'),
    ('08_announcements.jpg',15,'查询巨潮及上交所公告，选择原件加入本地资料库。','按日期过滤并保留来源；接口受限时提示列表不完整。'),
    ('09_import.jpg',15,'陌生文字型PDF或正文可导入、检索、引用与回看。','新报告结构化指标保留待核验；扫描资料需另行OCR。'),
    (None,18,'以证据立论，以反证校准。','让投资判断能够检查、能够追问，也能被后续变化检验。'),
]

def centered(draw,y,text,font,color):
    width=draw.textlength(text,font=font)
    if width>SIZE[0]-60:raise ValueError('Caption too wide: '+text)
    draw.text(((SIZE[0]-width)/2,y),text,font=font,fill=color)

def build(ffmpeg):
    FRAMES.mkdir(parents=True,exist_ok=True)
    regular=ImageFont.truetype(FONT,22);small=ImageFont.truetype(FONT,14)
    title=ImageFont.truetype(BOLD,64);subtitle=ImageFont.truetype(BOLD,32)
    files=[]
    for i,(screen,duration,line1,line2) in enumerate(SCENES):
        im=Image.new('RGB',SIZE,GREEN);d=ImageDraw.Draw(im)
        if screen:
            shot=Image.open(SCREENS/screen).convert('RGB');shot.thumbnail((1280,716),Image.Resampling.LANCZOS)
            im.paste(shot,((1280-shot.width)//2,0));d=ImageDraw.Draw(im)
            centered(d,720,line1,regular,'white');centered(d,749,line2,regular,'white')
        else:
            d.rectangle((70,92,160,97),fill=GOLD)
            d.text((70,128),'THESISLENS / 第六赛道',font=regular,fill=LIGHT)
            centered(d,265,line1,title,'white');centered(d,380,line2,subtitle,GOLD)
            if i==0:
                centered(d,480,'可运行原型 V0.4 / 2026年10月7日',regular,LIGHT)
                centered(d,525,'界面实拍字幕演示 · 无配音 · 非实时连续录屏',regular,LIGHT)
            else:
                centered(d,490,'52项自动测试通过 / 20项升级接口检查通过',regular,LIGHT)
                centered(d,535,'20题页面命中：关键词14/20，增强19/20（3题降级）',regular,LIGHT)
                centered(d,578,'开发题集非独立盲测，案例与估值假设仍需团队复审。',regular,LIGHT)
                centered(d,660,'github.com/Phosper/ThesisLens',regular,GOLD)
        centered(d,783,'知衡 V0.4 / 真实界面截图编排 / 历史模型记录 / 团队信息待补齐',small,LIGHT)
        file=FRAMES/f'frame_{i:02d}.png';im.save(file);files.append((file,duration))
    manifest=FRAMES/'frames.txt'
    manifest.write_text(''.join(f"file '{f.name}'\nduration {duration}\n" for f,duration in files)+f"file '{files[-1][0].name}'\n",'utf-8')
    total=sum(x[1] for x in files)
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(manifest),'-vf','fps=24','-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-an','-t',str(total),'-movflags','+faststart',str(OUT)],check=True)
    record={'filename':OUT.name,'duration_seconds':total,'width':1280,'height':800,'fps':24,'codec':'H.264','bytes':OUT.stat().st_size,'audio':False,'note':'真实界面截图编排的字幕演示，非实时连续录屏；展示历史模型记录，未对复核问题作专家签认。'}
    assert total<=300 and OUT.stat().st_size<500*1024*1024
    (OUT.parent/'video_metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ffmpeg',default=shutil.which('ffmpeg'));a=p.parse_args()
    if not a.ffmpeg:p.error('Install FFmpeg or specify --ffmpeg')
    build(a.ffmpeg)
