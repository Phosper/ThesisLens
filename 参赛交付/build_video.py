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
SCREENS=ROOT/'知衡初版/demo/screens_v05'
FRAMES=ROOT/'tmp/video'
OUT=ROOT/'参赛交付/知衡_项目简介.mp4'
FONT='C:/Windows/Fonts/msyh.ttc';BOLD='C:/Windows/Fonts/msyhbd.ttc'
SIZE=(1280,800)
GREEN='#174b43';LIGHT='#f5f6ef';GOLD='#d4bc7d'

SCENES=[
    (None,10,'知衡','融合证据链与反向验证的买方投研智能体'),
    ('01_workbench.jpg',18,'固定公司、研究时点与投资目标，组织研究证据。','期限、投入和损失约束为竞赛演示假设。'),
    ('02_depth.jpg',18,'财务解剖保留合并口径、原值、公式和物理页。','半年余额变动是期末对期初，不能与营收同比混比。'),
    ('03_valuation.jpg',25,'参考PE使用保存日期的A股报价与所选股数。','8 / 12 / 16倍依据未完成金融复核，仍为演示假设。'),
    ('04_decision.jpg',30,'投资判断列出条件、情景回报、退出和证据缺口。','依据未核验或下行情景超过约束时，明确暂缓判断。'),
    ('05_brief.jpg',18,'简略版优先展示判断、关键风险和未决事项。','切换展示不重新生成，重大问题持续保留。'),
    ('06_full.jpg',18,'详细版展开同一结果的财务、估值和完整证据。','Markdown与打印跟随视图，JSON保留完整快照。'),
    ('07_logic.jpg',22,'T编号连接经营假设、风险、失效条件与跟踪。','符合假设的数据是支持，反证须与原预测方向相反。'),
    ('08_trace.jpg',25,'真实模型的规划、检索、写作和有限修订逐步留痕。','展示保存记录；模型复核与规则检查分别记录。'),
    ('09_review.jpg',20,'金融人工核验登记支持或反证，程序不代签认。','结构分不代表事实正确率，剩余复核意见保留。'),
    ('10_announcements.jpg',15,'查询官方公告，按来源和截止日选择原件。','列表可能不完整；查询与选择导入由使用者操作。'),
    ('11_import.jpg',15,'陌生文字型资料可导入、检索、引用与回看。','未登记指标仍待核验；新扫描资料需另行OCR。'),
    (None,16,'以证据立论，以反证校准。','让研究判断能够回看依据，并接受后续检验。'),
]

def centered(draw,y,text,font,color):
    width=draw.textlength(text,font=font)
    if width>SIZE[0]-60:raise ValueError('Caption too wide: '+text)
    draw.text(((SIZE[0]-width)/2,y),text,font=font,fill=color)

def build(ffmpeg):
    acceptance=json.loads((ROOT/'知衡初版/V0.5验收记录.json').read_text('utf-8'))
    regression=acceptance['regression_tests']['passed']
    case=json.loads((ROOT/'知衡初版/demo/case_model_v05.json').read_text('utf-8'))
    runtime=f"保存案例：{case['duration_seconds']:.2f}秒 / {len(case['model_calls'])}次成功模型调用"
    scenes=list(SCENES)
    scenes[8]=(scenes[8][0],scenes[8][1],scenes[8][2],runtime+'；复核仍需人审。')
    FRAMES.mkdir(parents=True,exist_ok=True)
    regular=ImageFont.truetype(FONT,22);small=ImageFont.truetype(FONT,14)
    title=ImageFont.truetype(BOLD,64);subtitle=ImageFont.truetype(BOLD,32)
    files=[]
    for i,(screen,duration,line1,line2) in enumerate(scenes):
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
                centered(d,480,'可运行原型 V0.5 / 2026年10月12日',regular,LIGHT)
                centered(d,525,'界面实拍字幕演示 · 无配音 · 非实时连续录屏',regular,LIGHT)
            else:
                centered(d,490,f'{regression}项自动检查通过 / 新版真实模型流程已验收',regular,LIGHT)
                centered(d,535,'干净安装与陌生题已测试；同一电脑，非独立盲测。',regular,LIGHT)
                centered(d,578,'金融依据和剩余意见仍待人工核验。',regular,LIGHT)
                centered(d,660,'github.com/Phosper/ThesisLens',regular,GOLD)
        centered(d,783,'知衡 V0.5 / 真实界面截图编排 / 保存模型记录 / 非实时连续录屏',small,LIGHT)
        file=FRAMES/f'frame_{i:02d}.png';im.save(file);files.append((file,duration))
    manifest=FRAMES/'frames.txt'
    manifest.write_text(''.join(f"file '{f.name}'\nduration {duration}\n" for f,duration in files)+f"file '{files[-1][0].name}'\n",'utf-8')
    total=sum(x[1] for x in files)
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(manifest),'-vf','fps=24','-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-an','-t',str(total),'-movflags','+faststart',str(OUT)],check=True)
    record={'filename':OUT.name,'version':'0.5.0','case_id':case['id'],'duration_seconds':total,'width':1280,'height':800,'fps':24,'codec':'H.264','bytes':OUT.stat().st_size,'audio':False,'note':'真实界面截图编排的字幕演示，非实时连续录屏；展示保存的真实模型输出，未对复核问题作专家签认。'}
    assert total<=300 and OUT.stat().st_size<500*1024*1024
    (OUT.parent/'video_metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ffmpeg',default=shutil.which('ffmpeg'));a=p.parse_args()
    if not a.ffmpeg:p.error('Install FFmpeg or specify --ffmpeg')
    build(a.ffmpeg)
