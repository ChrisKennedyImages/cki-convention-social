"""The look of eventcaliber.com: black, greys and white with one cyan, built like a camera viewfinder.

Plain strings on purpose (no template engine): CSS, JS and the page shell. Motion
is CSS and a little vanilla JS, and all of it stops for visitors who ask for
reduced motion.
"""
from __future__ import annotations

CSS = r"""
@font-face{font-family:"Michroma";src:url(/assets/fonts/Michroma-Regular.ttf) format("truetype");font-display:swap}
@font-face{font-family:"Inter Tight";src:url(/assets/fonts/InterTight-Light.ttf) format("truetype");font-weight:300;font-display:swap}
@font-face{font-family:"Inter Tight";src:url(/assets/fonts/InterTight-Regular.ttf) format("truetype");font-weight:400;font-display:swap}
@font-face{font-family:"Inter Tight";src:url(/assets/fonts/InterTight-SemiBold.ttf) format("truetype");font-weight:600;font-display:swap}
@font-face{font-family:"Unbounded";src:url(/assets/fonts/Unbounded-ExtraBold.ttf) format("truetype");font-weight:800;font-display:swap}
@font-face{font-family:"JetBrains Mono";src:url(/assets/fonts/JetBrainsMono-Medium.ttf) format("truetype");font-weight:500;font-display:swap}
:root{color-scheme:dark;--k:#0A0A0B;--g1:#121214;--g2:#1C1C20;--g3:#2C2C31;--g4:#8C8C93;--g5:#C8C8CD;--w:#F3F3F1;--c:#00E1FF;
--display:"Michroma","Arial Black",sans-serif;--body:"Inter Tight",system-ui,-apple-system,Helvetica,Arial,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
--pad:clamp(18px,4vw,56px)}
*{box-sizing:border-box}html{background:var(--k)}body{margin:0;background:var(--k);color:var(--w);font:300 18px/1.6 var(--body);overflow-x:hidden}
a{color:inherit;text-decoration:none}img{display:block;max-width:100%}
::selection{background:var(--c);color:var(--k)}
.mono{font:500 12px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase}
.c{color:var(--c)}.g{color:var(--g4)}
/* grain + cursor */
.grain{pointer-events:none;position:fixed;inset:-50%;z-index:60;opacity:.07;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");animation:grain 1s steps(6) infinite}
@keyframes grain{0%{transform:translate(0,0)}20%{transform:translate(-3%,2%)}40%{transform:translate(2%,-3%)}60%{transform:translate(-2%,-1%)}80%{transform:translate(3%,3%)}100%{transform:translate(0,0)}}
.cursor{position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border:1px solid rgba(243,243,241,.5);z-index:70;pointer-events:none;transition:width .25s,height .25s,margin .25s,border-color .25s,opacity .3s;display:none;opacity:0}
.cursor.live{opacity:1}
.cursor:before,.cursor:after{content:"";position:absolute;background:var(--c)}
.cursor:before{left:50%;top:50%;width:4px;height:4px;margin:-2px 0 0 -2px;border-radius:50%}
.cursor.big{width:76px;height:76px;margin:-38px 0 0 -38px;border-color:var(--c)}
@media (pointer:fine){.cursor{display:block}body{cursor:none}a,button,label,input,select,textarea{cursor:none}}
/* header */
.top{position:fixed;inset:0 0 auto;z-index:50;display:flex;align-items:center;gap:28px;padding:18px var(--pad);transition:background .3s,padding .3s}
.top.solid{background:rgba(10,10,11,.86);backdrop-filter:blur(10px);padding-top:12px;padding-bottom:12px;border-bottom:1px solid var(--g3)}
.top .logo svg{height:46px;width:auto}
.top nav{margin-left:auto;display:flex;gap:26px}.top nav a{color:var(--g5)}.top nav a:hover{color:var(--w)}
.top nav a b{color:var(--c);font-weight:500}
.btn{display:inline-flex;align-items:center;gap:12px;border:1px solid var(--w);padding:15px 22px;font:500 12px var(--mono);letter-spacing:.16em;text-transform:uppercase;transition:background .25s,color .25s,border-color .25s;background:transparent;color:var(--w)}
.btn:hover{background:var(--c);border-color:var(--c);color:var(--k)}.btn .arr{transition:transform .25s}.btn:hover .arr{transform:translate(3px,-3px)}
.btn.fill{background:var(--w);color:var(--k)}.btn.fill:hover{background:var(--c)}
/* hero */
.hero{position:relative;height:100svh;min-height:640px;overflow:hidden;display:flex;align-items:flex-end}
.hero .img{position:absolute;inset:0}.hero .img img{width:100%;height:100%;object-fit:cover;animation:push 18s ease-out forwards;filter:saturate(.9) contrast(1.05)}
@keyframes push{from{transform:scale(1.14)}to{transform:scale(1)}}
.hero:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(10,10,11,.55) 0%,rgba(10,10,11,0) 30%,rgba(10,10,11,.25) 55%,rgba(10,10,11,.96) 100%)}
.vf{position:absolute;inset:clamp(70px,9vh,110px) var(--pad) clamp(24px,4vh,40px);z-index:2;pointer-events:none}
.vf i{position:absolute;width:44px;height:44px;border:0 solid var(--w)}
.vf i:nth-child(1){left:0;top:0;border-width:2px 0 0 2px}.vf i:nth-child(2){right:0;top:0;border-width:2px 2px 0 0}
.vf i:nth-child(3){left:0;bottom:0;border-width:0 0 2px 2px}.vf i:nth-child(4){right:0;bottom:0;border-width:0 2px 2px 0}
.vf .cross{position:absolute;left:50%;top:42%;width:22px;height:22px;margin:-11px}
.vf .cross:before,.vf .cross:after{content:"";position:absolute;background:rgba(243,243,241,.7)}.vf .cross:before{left:10px;top:0;width:2px;height:22px}.vf .cross:after{top:10px;left:0;height:2px;width:22px}
.vf .focus{position:absolute;left:58%;top:22%;width:120px;height:86px;border:2px solid var(--c);animation:af 1.6s cubic-bezier(.2,.8,.2,1) .4s both}
@keyframes af{0%{transform:scale(2.2);opacity:0}55%{transform:scale(.9);opacity:1}70%{transform:scale(1.04)}100%{transform:scale(1)}}
.hud{position:absolute;z-index:3;color:var(--w)}.hud.tl{left:calc(var(--pad) + 60px);top:clamp(78px,10vh,118px)}.hud.tr{right:calc(var(--pad) + 60px);top:clamp(78px,10vh,118px);text-align:right}
.hud.br{right:calc(var(--pad) + 60px);bottom:clamp(30px,5vh,52px)}
.rec:before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--c);margin-right:10px;vertical-align:1px;animation:blink 1.2s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
.hero .copy{position:relative;z-index:3;padding:0 calc(var(--pad) + 60px) clamp(64px,10vh,110px);width:100%}
.mega{font:400 clamp(40px,min(8.6vw,12.5vh),150px)/.92 var(--display);letter-spacing:-.02em;margin:0;text-transform:uppercase}
.mega span{display:block;overflow:hidden}.mega span em{display:block;font-style:normal;transform:translateY(105%);animation:up 1s cubic-bezier(.2,.8,.2,1) forwards}
.mega span:nth-child(2) em{animation-delay:.12s}.mega span:nth-child(3) em{animation-delay:.24s}
.mega .o{color:transparent;-webkit-text-stroke:1.5px var(--w)}.mega b{color:var(--c);font-weight:400}
@keyframes up{to{transform:none}}
.hero .row{display:flex;gap:32px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;margin-top:28px}
.hero .lede{max-width:520px;margin:0;color:var(--g5);font-size:19px}
/* ticker */
.ticker{border-block:1px solid var(--g3);overflow:hidden;padding:22px 0;background:var(--k)}
.ticker .track{display:flex;width:max-content;animation:tick 38s linear infinite}
.ticker.rev .track{animation-direction:reverse;animation-duration:46s}
.ticker span{font:400 clamp(26px,3.6vw,54px)/1 var(--display);text-transform:uppercase;padding:0 26px;white-space:nowrap}
.ticker span.o{color:transparent;-webkit-text-stroke:1px var(--g4)}.ticker span.dot{color:var(--c);padding:0 6px}
@keyframes tick{to{transform:translateX(-50%)}}
/* sections */
section{position:relative;padding:clamp(80px,12vw,160px) var(--pad)}
.kick{display:flex;gap:14px;align-items:center;margin-bottom:28px}.kick:before{content:"";width:28px;height:1px;background:var(--c)}
h2{font:400 clamp(32px,5.4vw,84px)/.98 var(--display);text-transform:uppercase;letter-spacing:-.02em;margin:0}
h2 .o{color:transparent;-webkit-text-stroke:1.2px var(--w)}
.js .rv{opacity:0;transform:translateY(40px);transition:opacity 1s cubic-bezier(.2,.8,.2,1),transform 1s cubic-bezier(.2,.8,.2,1)}.js .rv.in{opacity:1;transform:none}
/* coverage index */
.index .head{display:grid;grid-template-columns:1fr minmax(260px,420px);gap:40px;align-items:end;margin-bottom:56px}
.index .head p{color:var(--g5);margin:0}
.list{border-top:1px solid var(--g3)}
.list a{display:grid;grid-template-columns:70px 1fr auto;align-items:center;gap:20px;padding:26px 0;border-bottom:1px solid var(--g3);position:relative;overflow:hidden}
.list a:before{content:"";position:absolute;inset:0;background:var(--c);transform:scaleY(0);transform-origin:bottom;transition:transform .45s cubic-bezier(.2,.8,.2,1);z-index:0}
.list a>*{position:relative;z-index:1;transition:color .3s,transform .45s}
.list a .t{font:400 clamp(20px,2.6vw,40px)/1.1 var(--display);text-transform:uppercase}
.list a:hover:before{transform:scaleY(1)}.list a:hover>*{color:var(--k)}.list a:hover .t{transform:translateX(14px)}
.peek{position:fixed;left:0;top:0;width:300px;height:380px;pointer-events:none;z-index:40;opacity:0;transform:translate(-50%,-50%) scale(.85);transition:opacity .25s,transform .25s;overflow:hidden;border:1px solid var(--w)}
.peek.on{opacity:1;transform:translate(-50%,-50%) scale(1)}.peek img{width:100%;height:100%;object-fit:cover}
/* reel */
.reel{padding:0}.reel .pin{position:sticky;top:0;height:100vh;overflow:hidden;display:flex;flex-direction:column;justify-content:center;padding-top:70px}
.reel .bar{display:flex;justify-content:space-between;padding:0 var(--pad);margin-bottom:26px}
.reel .track{display:flex;gap:18px;padding:0 var(--pad);will-change:transform}
.frame{flex:none;width:clamp(240px,min(34vw,46vh),520px)}.frame .ph{aspect-ratio:4/5;overflow:hidden;background:var(--g2)}
.frame img{width:100%;height:100%;object-fit:cover;transition:transform 1.2s cubic-bezier(.2,.8,.2,1)}.frame:hover img{transform:scale(1.06)}
.frame .cap{display:flex;justify-content:space-between;margin-top:12px;color:var(--g4)}
.sprocket{height:16px;background:radial-gradient(circle at 10px 8px,var(--k) 4px,transparent 5px) 0 0/22px 16px repeat-x,var(--g2);margin:0 var(--pad)}
/* delivery */
.deliver{display:grid;grid-template-columns:1.1fr .9fr;gap:60px;align-items:center}
.deliver .lines div{font:400 clamp(30px,5vw,78px)/1.02 var(--display);text-transform:uppercase}
.deliver .lines div:nth-child(2){color:transparent;-webkit-text-stroke:1.2px var(--w)}.deliver .lines div:nth-child(3){color:var(--c)}
.deliver p{color:var(--g5);max-width:520px}
.stack{position:relative;aspect-ratio:1/1.05}
.stack figure{position:absolute;margin:0;width:62%;aspect-ratio:4/5;overflow:hidden;border:6px solid var(--w);box-shadow:0 30px 60px rgba(0,0,0,.6);transition:transform 1.1s cubic-bezier(.2,.8,.2,1)}
.stack figure img{width:100%;height:100%;object-fit:cover}
.stack figure:nth-child(1){left:4%;top:10%;transform:rotate(-9deg)}.stack figure:nth-child(2){left:20%;top:4%;transform:rotate(3deg)}.stack figure:nth-child(3){left:34%;top:14%;transform:rotate(11deg)}
.js .stack.rv:not(.in) figure{transform:rotate(0) translateY(40px)}
.stamp{position:absolute;right:2%;bottom:6%;z-index:5;background:var(--c);color:var(--k);padding:10px 14px;transform:rotate(-4deg)}
/* venues */
.venues .grid{display:grid;grid-template-columns:1.5fr 1fr;gap:18px;margin-top:56px}
.venues figure{margin:0;position:relative;overflow:hidden;background:var(--g2)}.venues figure:first-child{grid-row:span 2;min-height:560px}
.venues figure{min-height:260px}.venues figure img{position:absolute;left:0;top:-12%;width:100%;height:124%;object-fit:cover;will-change:transform}
.venues figure .mono{position:absolute;left:14px;bottom:12px;background:rgba(10,10,11,.7);padding:6px 9px}
.venues .head{display:grid;grid-template-columns:1fr minmax(260px,420px);gap:40px;align-items:end}.venues .head p{color:var(--g5);margin:0}
/* process */
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid var(--g3);margin-top:56px}
.steps>div{padding:34px 30px 40px;border-right:1px solid var(--g3)}.steps>div:last-child{border-right:0}
.steps .n{font:400 64px/1 var(--display);color:transparent;-webkit-text-stroke:1px var(--g4);margin-bottom:26px}
.steps h3{font:600 22px/1.2 var(--body);margin:0 0 10px}.steps p{color:var(--g5);margin:0}
.steps>div:hover .n{-webkit-text-stroke-color:var(--c)}
/* cta */
.cta{text-align:center;border-top:1px solid var(--g3)}
.cta a.huge{display:inline-block;font:400 clamp(30px,6.6vw,120px)/.95 var(--display);text-transform:uppercase;letter-spacing:-.02em;position:relative}
.cta a.huge:after{content:"";position:absolute;left:0;right:0;bottom:-10px;height:6px;background:var(--c);transform:scaleX(.18);transform-origin:left;transition:transform .6s cubic-bezier(.2,.8,.2,1)}
.cta a.huge:hover:after{transform:scaleX(1)}
.cta p{color:var(--g5);max-width:560px;margin:34px auto 0}
/* footer */
footer{padding:60px var(--pad) 36px;border-top:1px solid var(--g3);overflow:hidden}
footer .big{font:400 clamp(30px,7vw,136px)/.9 var(--display);text-transform:uppercase;color:transparent;-webkit-text-stroke:1px var(--g3);white-space:nowrap;letter-spacing:-.03em}
footer .row{display:flex;flex-wrap:wrap;gap:22px 36px;justify-content:space-between;margin-top:30px;color:var(--g4)}
footer a:hover{color:var(--c)}
/* inner pages */
.page{padding-top:clamp(130px,16vh,170px)}
.page h1{font:400 clamp(40px,7vw,120px)/.94 var(--display);text-transform:uppercase;letter-spacing:-.02em;margin:0}
.page h1 .o{color:transparent;-webkit-text-stroke:1.4px var(--w)}.page h1 b{color:var(--c);font-weight:400}
.split2{display:grid;grid-template-columns:minmax(260px,.8fr) 1.2fr;gap:clamp(30px,6vw,90px);margin-top:60px;align-items:start}
.side{position:sticky;top:110px;border:1px solid var(--g3);padding:26px}
.side ol{list-style:none;padding:0;margin:18px 0 0;counter-reset:s}.side li{counter-increment:s;padding:14px 0;border-top:1px solid var(--g3);color:var(--g5)}
.side li:before{content:"0" counter(s);font:500 12px var(--mono);color:var(--c);margin-right:14px}
form.book{display:grid;grid-template-columns:1fr 1fr;gap:30px 26px}
form.book .full{grid-column:1/-1}
form.book .f label{display:block;margin-bottom:8px;color:var(--g4)}
form.book input,form.book select,form.book textarea{width:100%;background:transparent;color:var(--w);border:0;border-bottom:1px solid var(--g3);padding:10px 0 12px;font:300 20px var(--body);border-radius:0;transition:border-color .25s}
form.book select option{background:var(--k)}
form.book input:focus,form.book select:focus,form.book textarea:focus{outline:0;border-bottom-color:var(--c)}
form.book textarea{min-height:120px;resize:vertical}
.chips{display:flex;flex-wrap:wrap;gap:10px}
.chips label{position:relative}.chips input{position:absolute;opacity:0;pointer-events:none}
.chips span{display:inline-block;padding:11px 16px;border:1px solid var(--g3);font:500 12px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--g5);transition:all .2s}
.chips label:hover span{border-color:var(--g4);color:var(--w)}.chips input:checked+span{border-color:var(--c);color:var(--k);background:var(--c)}
.chips input:focus-visible+span{outline:2px solid var(--c);outline-offset:2px}
.hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.err{border:1px solid var(--c);padding:14px 18px;margin:0 0 30px;color:var(--w)}
.cal{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:40px 30px;margin-top:60px}
.month h3{font:500 13px var(--mono);letter-spacing:.14em;text-transform:uppercase;margin:0 0 14px;color:var(--g5)}
.days{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
.days span{aspect-ratio:1;display:flex;align-items:center;justify-content:center;border:1px solid var(--g2);font:500 13px var(--mono);color:var(--g5)}
.days span.h{border:0;color:var(--g4);font-size:11px}.days span.x{border:0}
.days span.b{color:var(--k);background:repeating-linear-gradient(135deg,var(--c) 0 4px,#00B8D4 4px 8px);border-color:var(--c)}
.days span.t{border-color:var(--w);color:var(--w)}
.legend{display:flex;gap:26px;margin-top:26px;color:var(--g4)}.legend i{display:inline-block;width:14px;height:14px;vertical-align:-2px;margin-right:8px;border:1px solid var(--g2)}
.legend i.b{background:var(--c);border-color:var(--c)}
.prose{max-width:760px;margin-top:50px}.prose h3{font:600 22px var(--body);margin:44px 0 10px}.prose p{color:var(--g5)}
.preview{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:80;background:var(--c);color:var(--k);padding:9px 16px}
@media (max-width:900px){.top nav{display:none}.index .head,.venues .head,.deliver,.split2{grid-template-columns:1fr}.steps{grid-template-columns:1fr}
.steps>div{border-right:0;border-bottom:1px solid var(--g3)}.venues .grid{grid-template-columns:1fr}.venues figure:first-child{grid-row:auto}
.reel .pin{position:relative;height:auto;padding:90px 0}.reel .track{overflow-x:auto;scroll-snap-type:x mandatory;transform:none!important}
.frame{width:78vw;scroll-snap-align:start}.side{position:relative;top:0}form.book{grid-template-columns:1fr}.hud.tr{display:none}
.vf .focus{left:60%;top:16%;width:70px;height:52px}.vf .cross,.hud.tl{display:none}
.hero .copy{padding:0 calc(var(--pad) + 14px) 76px}.mega{font-size:clamp(30px,10.4vw,64px)}.hero .lede{font-size:16px}.hero .row{margin-top:18px;gap:20px}
.vf i{width:28px;height:28px}.list a{grid-template-columns:44px 1fr auto}.top .btn{padding:12px 14px}}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}.mega span em{transform:none}.rv{opacity:1;transform:none}}
"""

JS = r"""
(()=>{document.documentElement.classList.add('js');const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;const fine=matchMedia('(pointer: fine)').matches;
const top=document.querySelector('.top');const onScroll=()=>top&&top.classList.toggle('solid',scrollY>40);addEventListener('scroll',onScroll,{passive:true});onScroll();
// reveal
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.14});
document.querySelectorAll('.rv').forEach(el=>io.observe(el));
// timecode + frame counter
const tc=document.getElementById('tc'),fr=document.getElementById('fr');
if(tc&&!reduce){const t0=performance.now();const tick=n=>{const s=(n-t0)/1000;const f=Math.floor((s%1)*24);const p=v=>String(v).padStart(2,'0');
tc.textContent=p(Math.floor(s/3600))+':'+p(Math.floor(s/60)%60)+':'+p(Math.floor(s)%60)+':'+p(f);requestAnimationFrame(tick)};requestAnimationFrame(tick)}
if(fr)addEventListener('scroll',()=>{fr.textContent=String(1+Math.floor(scrollY/90)).padStart(4,'0')},{passive:true});
// cursor
const cur=document.querySelector('.cursor');
if(cur&&fine){addEventListener('mousemove',e=>{cur.classList.add('live');cur.style.transform='translate('+e.clientX+'px,'+e.clientY+'px)'});
document.querySelectorAll('a,button,.chips label').forEach(a=>{a.addEventListener('mouseenter',()=>cur.classList.add('big'));a.addEventListener('mouseleave',()=>cur.classList.remove('big'))})}
// coverage peek
const peek=document.querySelector('.peek');
if(peek&&fine){const img=peek.querySelector('img');document.querySelectorAll('.list a').forEach(a=>{
a.addEventListener('mouseenter',()=>{if(a.dataset.img){img.src=a.dataset.img;peek.classList.add('on')}});a.addEventListener('mouseleave',()=>peek.classList.remove('on'))});
addEventListener('mousemove',e=>{peek.style.left=e.clientX+40+'px';peek.style.top=e.clientY+'px'})}
// horizontal reel
const reel=document.querySelector('.reel'),track=reel&&reel.querySelector('.track');
const size=()=>{if(!reel||innerWidth<=900){if(reel)reel.style.height='';return}reel.style.height=(track.scrollWidth-innerWidth+innerHeight+120)+'px'};
if(reel&&!reduce){size();addEventListener('resize',size);addEventListener('scroll',()=>{if(innerWidth<=900)return;const r=reel.getBoundingClientRect();
const max=track.scrollWidth-innerWidth;const p=Math.min(1,Math.max(0,-r.top/(reel.offsetHeight-innerHeight)));track.style.transform='translateX('+(-p*max)+'px)'},{passive:true})}
// parallax
const par=[...document.querySelectorAll('[data-speed]')];
const move=()=>par.forEach(el=>{const r=el.parentElement.getBoundingClientRect();const d=(r.top+r.height/2-innerHeight/2)*parseFloat(el.dataset.speed);el.style.transform='translateY('+Math.max(-24,Math.min(24,d))+'px)'});
if(par.length&&!reduce){addEventListener('scroll',move,{passive:true});move()}
})();
"""


def shell(*, title: str, description: str, body: str, mark_svg: str, brand: str, legal: str, email: str,
          preview: bool, canonical: str, jsonld: str = "", og_image: str = "",
          sections: tuple = ("work", "venues")) -> str:
    """`sections`: the photo sections the home page has; the menu links only to those (a site built
    before any photo is cleared has neither)."""
    links = [("/#coverage", "01", "Coverage"), ("/#work", "02", "Work"), ("/#venues", "03", "Venues"),
             ("/availability/", "04", "Availability")]
    nav = "".join(f'<a href="{h}"><b>{n}</b> {label}</a>' for h, n, label in links
                  if not h.startswith("/#") or h[2:] == "coverage" or h[2:] in sections)
    stamp = '<div class="preview mono">Preview, not live</div>' if preview else ""
    robots = '<meta name="robots" content="noindex,nofollow">' if preview else ""
    og = f'<meta property="og:image" content="{og_image}">' if og_image else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<meta name="description" content="{description}"><link rel="canonical" href="{canonical}">{robots}
<meta property="og:title" content="{title}"><meta property="og:description" content="{description}"><meta property="og:type" content="website">{og}
<meta name="theme-color" content="#0A0A0B"><link rel="icon" href="/assets/mark.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/site.css"><script>document.documentElement.classList.add("js")</script>{jsonld}
</head><body><div class="grain" aria-hidden="true"></div><div class="cursor" aria-hidden="true"></div>
<header class="top"><a class="logo" href="/" aria-label="{brand} home">{mark_svg}</a>
<nav class="mono">{nav}</nav>
<a class="btn" href="/book/">Request a quote <span class="arr">&#8599;</span></a></header>
<main>{body}</main>
<footer><div class="big" aria-hidden="true">{brand}</div><div class="row mono"><span>{brand}, a brand of {legal}</span>
<a href="/book/">Request a quote</a><a href="/availability/">Availability</a><a href="/privacy/">Privacy and photo removal</a><a href="mailto:{email}">{email}</a></div></footer>
{stamp}<script src="/assets/site.js" defer></script></body></html>"""
