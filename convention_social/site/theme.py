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
/* header (2026-10-14): words on an iPad and a computer; on a phone the logo, the phone number and the quote, and the bar at the bottom */
.top{position:fixed;inset:0 0 auto;z-index:50;display:flex;align-items:center;gap:22px;padding:18px var(--pad);transition:background .3s,padding .3s}
.top.solid{background:rgba(10,10,11,.86);backdrop-filter:blur(10px);padding-top:12px;padding-bottom:12px;border-bottom:1px solid var(--g3)}
.top .logo svg{height:46px;width:auto}
.top nav{margin-left:auto;display:flex;gap:clamp(14px,2vw,26px)}.top nav a{color:var(--g5);min-height:44px;display:inline-flex;align-items:center;padding:0 2px}
.top nav a:hover,.top nav a[aria-current]{color:var(--w)}.top nav a[aria-current]{box-shadow:inset 0 -2px 0 var(--c)}
.top .tel{color:var(--g5);white-space:nowrap;min-height:44px;display:inline-flex;align-items:center;gap:8px}.top .tel:hover{color:var(--c)}
.top .tel svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.tabbar{display:none}
.btn{display:inline-flex;align-items:center;gap:12px;border:1px solid var(--w);padding:15px 22px;font:500 12px var(--mono);letter-spacing:.16em;text-transform:uppercase;transition:background .25s,color .25s,border-color .25s;background:transparent;color:var(--w)}
.btn:hover{background:var(--c);border-color:var(--c);color:var(--k)}.btn .arr{transition:transform .25s}.btn:hover .arr{transform:translate(3px,-3px)}
.btn.fill{background:var(--w);color:var(--k)}.btn.fill:hover{background:var(--c)}
/* hero (2026-10-14): the photo, then the words on a solid band under it; nothing is written over the picture. No section
   padding: the photo runs edge to edge under the bar, and the band carries its own */
.hero{position:relative;padding:0}
.hero .photo{position:relative;height:56svh;min-height:400px;max-height:820px;overflow:hidden;background:var(--g1)}
.hero .img{position:absolute;inset:0}.hero .img img{width:100%;height:100%;object-fit:cover;animation:push 18s ease-out forwards;filter:brightness(1.24) saturate(1.35) contrast(1.04)}
@keyframes push{from{transform:scale(1.14)}to{transform:scale(1)}}
.hero .photo:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(10,10,11,.28) 0%,rgba(10,10,11,0) 26%,rgba(10,10,11,0) 72%,rgba(10,10,11,.5) 100%)}
.hero canvas.web{position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none;mix-blend-mode:screen;opacity:.7}
.vf{position:absolute;inset:clamp(70px,9vh,110px) var(--pad) clamp(24px,4vh,40px);z-index:2;pointer-events:none}
.vf i{position:absolute;width:44px;height:44px;border:0 solid var(--w)}
.vf i:nth-child(1){left:0;top:0;border-width:2px 0 0 2px}.vf i:nth-child(2){right:0;top:0;border-width:2px 2px 0 0}
.vf i:nth-child(3){left:0;bottom:0;border-width:0 0 2px 2px}.vf i:nth-child(4){right:0;bottom:0;border-width:0 2px 2px 0}
@keyframes af{0%{transform:scale(2.2);opacity:0}55%{transform:scale(.9);opacity:1}70%{transform:scale(1.04)}100%{transform:scale(1)}}
.rec:before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--c);margin-right:10px;vertical-align:1px;animation:blink 1.2s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
.hero .copy{position:relative;z-index:3;padding:clamp(34px,5vw,64px) var(--pad) clamp(44px,6vw,80px);background:var(--k)}
.mega{font:400 clamp(40px,min(7vw,9.5vh),124px)/.92 var(--display);letter-spacing:-.02em;margin:0;text-transform:uppercase}
.mega span{display:block;overflow:hidden}.mega span em{display:block;font-style:normal;transform:translateY(105%);animation:up 1s cubic-bezier(.2,.8,.2,1) forwards}
.mega span:nth-child(2) em{animation-delay:.12s}.mega span:nth-child(3) em{animation-delay:.24s}
.mega .o{color:transparent;-webkit-text-stroke:1.5px var(--w)}.mega b{color:var(--c);font-weight:400}
@keyframes up{to{transform:none}}
.hero .first{font:400 clamp(19px,1.6vw,24px)/1.45 var(--body);color:var(--w);max-width:780px;margin:26px 0 0}
.hero .row{display:flex;gap:32px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;margin-top:22px}
.hero .lede{max-width:560px;margin:0;color:var(--g5);font-size:18px}
/* ticker */
/* the ticker fades out over the page's gutter at both ends (Chris, 2026-10-14: "the top website scroller cuts off on the left
   side when viewing on a computer"): the word leaving at the left was sliced flat at the screen's edge while everything else
   on the page sits behind the gutter */
.ticker{border-block:1px solid var(--g3);overflow:hidden;padding:22px 0;background:var(--k);-webkit-mask-image:linear-gradient(90deg,transparent,#000 var(--pad),#000 calc(100% - var(--pad)),transparent);mask-image:linear-gradient(90deg,transparent,#000 var(--pad),#000 calc(100% - var(--pad)),transparent)}
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
.list a .t em{display:block;font:300 clamp(14px,1.1vw,17px)/1.45 var(--body);text-transform:none;font-style:normal;color:var(--g4);margin-top:8px;max-width:620px}
.list a:hover:before{transform:scaleY(1)}.list a:hover>*{color:var(--k)}.list a:hover .t{transform:translateX(14px)}
/* work (2026-10-14): a strip that rolls on its own, pauses under a finger or the pointer, moves one frame per arrow, and never moves with the page scroll.
   Every frame has its photo's own shape (--ar, width over height, set by the build): a wide photo is wide, a tall one tall, nothing is cropped
   (Chris, 2026-10-14: "the horizontal images must not be cropped anywhere on any device"); only the hero may be */
.reel{padding:clamp(60px,8vw,120px) 0}
.reel .bar{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:0 var(--pad);margin-bottom:22px;flex-wrap:wrap}
.reel .bar .hint{color:var(--g4)}
.reel .arrows{display:flex;gap:10px}.reel .arrows button{width:44px;height:44px;border:1px solid var(--g3);background:transparent;color:var(--w);font:400 18px/1 var(--mono);cursor:pointer;transition:border-color .25s,color .25s}
.reel .arrows button:hover,.reel .arrows button:focus-visible{border-color:var(--c);color:var(--c);outline:0}
.reel .track{display:flex;gap:18px;padding:0 var(--pad);overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none;align-items:flex-end}.reel .track::-webkit-scrollbar{display:none}
.frame{flex:none;--h:clamp(300px,54vh,600px)}.frame a{display:block}
.frame .ph{width:min(calc(var(--h) * var(--ar,0.8)),calc(100vw - 2 * var(--pad)));aspect-ratio:var(--ar,0.8);background:var(--g2)}
.frame img{width:100%;height:100%;object-fit:contain;transition:filter .4s}.frame:hover img{filter:brightness(1.08)}
.frame .cap{display:flex;justify-content:space-between;margin-top:12px;color:var(--g4)}
.sprocket{height:16px;background:radial-gradient(circle at 10px 8px,var(--k) 4px,transparent 5px) 0 0/22px 16px repeat-x,var(--g2);margin:0 var(--pad)}
/* delivery */
.deliver{display:grid;grid-template-columns:1.1fr .9fr;gap:60px;align-items:center}
.deliver .lines div{font:400 clamp(30px,5vw,78px)/1.02 var(--display);text-transform:uppercase}
.deliver .lines div:nth-child(2){color:transparent;-webkit-text-stroke:1.2px var(--w)}.deliver .lines div:nth-child(3){color:var(--c)}
.deliver p{color:var(--g5);max-width:520px}
.stack{position:relative;aspect-ratio:1/1.05}
.stack figure{position:absolute;margin:0;width:62%;aspect-ratio:var(--ar,0.8);overflow:hidden;border:6px solid var(--w);box-shadow:0 30px 60px rgba(0,0,0,.6);transition:transform 1.1s cubic-bezier(.2,.8,.2,1)}
.stack figure img{width:100%;height:100%;object-fit:contain}
.stack figure:nth-child(1){left:4%;top:10%;transform:rotate(-9deg)}.stack figure:nth-child(2){left:20%;top:4%;transform:rotate(3deg)}.stack figure:nth-child(3){left:34%;top:14%;transform:rotate(11deg)}
.js .stack.rv:not(.in) figure{transform:rotate(0) translateY(40px)}
.stamp{position:absolute;right:2%;bottom:6%;z-index:5;background:var(--c);color:var(--k);padding:10px 14px;transform:rotate(-4deg)}
/* venues: each building in its own shape, whole (2026-10-14); the parallax that needed a taller picture to slide is gone */
.venues .grid{columns:2;gap:18px;margin-top:56px}
.venues figure{margin:0 0 18px;break-inside:avoid;position:relative;overflow:hidden;background:var(--g2);aspect-ratio:var(--ar,1.5)}
.venues figure img{width:100%;height:100%;object-fit:contain}
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
/* footer (2026-10-14): every page, the coverage, the contact and the legal line; it was one line */
footer{padding:60px var(--pad) 36px;border-top:1px solid var(--g3);overflow:hidden}
footer .big{font:400 clamp(30px,7vw,136px)/.9 var(--display);text-transform:uppercase;color:transparent;-webkit-text-stroke:1px var(--g3);white-space:nowrap;letter-spacing:-.03em}
footer .foot{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;gap:36px;margin-top:36px}
footer h4{font:500 12px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--c);margin:0 0 14px}
footer ul{list-style:none;margin:0;padding:0}footer li{margin:0 0 8px}footer li a{color:var(--g5);display:inline-block;padding:4px 0}
footer .about{color:var(--g5);max-width:420px;margin:0}
footer .legal{margin-top:40px;padding-top:20px;border-top:1px solid var(--g3);color:var(--g4);display:flex;flex-wrap:wrap;gap:12px 30px;justify-content:space-between}
footer a:hover{color:var(--c)}
/* coverage pages and the contact page (2026-10-14) */
.page .first{font:400 clamp(19px,1.6vw,24px)/1.45 var(--body);color:var(--w);max-width:760px;margin:26px 0 0}  /* every inner page's lead line, the same (2026-10-14) */
.cover .prose{margin-top:24px}.cover .grid{columns:3;gap:18px;margin-top:50px}
.cover figure{margin:0 0 18px;break-inside:avoid;aspect-ratio:var(--ar,0.8);overflow:hidden;background:var(--g2)}.cover figure img{width:100%;height:100%;object-fit:contain}
.cover .more{margin-top:70px}
.contact .hand{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:40px;max-width:1000px}
.contact .hand>div{border:1px solid var(--g3);padding:26px}
.contact .hand a.l{display:block;font:400 clamp(16px,1.6vw,24px)/1.3 var(--display);margin-top:12px;overflow-wrap:anywhere}.contact .hand a.l:hover{color:var(--c)}  /* 2026-10-14: at 30px the address broke mid-word on an iPad and a computer */
/* inner pages */
.page{padding-top:clamp(130px,16vh,170px);padding-bottom:clamp(60px,8vw,110px)}  /* a short page no longer ends in an empty band before the footer (2026-10-14) */
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
/* the iPad (2026-10-14): the computer's layout with closer spacing, the menu in words, the phone number in the footer */
@media (min-width:761px) and (max-width:1100px){.top{gap:16px}.top .logo svg{height:40px}.top .tel{display:none}.top nav{gap:12px}.top .btn{padding:13px 14px}
.hero .photo{height:54svh;min-height:380px}.mega{font-size:clamp(36px,7.4vw,84px)}
.frame{--h:clamp(280px,40vh,480px)}.cover .grid{columns:2}footer .foot{grid-template-columns:1fr 1fr}}
/* the phone (2026-10-14): one column, the bar at the bottom, the hero words under the photo on the first screen */
@media (max-width:760px){.top{gap:10px}.top nav{display:none}.top .logo svg{height:36px}.top .tel{margin-left:auto}.top .btn{padding:12px 14px}.top .btn .long{display:none}
.tabbar{position:fixed;left:0;right:0;bottom:0;z-index:55;display:flex;justify-content:space-around;align-items:stretch;gap:4px;padding:8px 6px calc(8px + env(safe-area-inset-bottom));background:rgba(10,10,11,.94);backdrop-filter:blur(12px);border-top:1px solid var(--g3)}
.tabbar a{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;min-height:48px;color:var(--g5);font:500 10px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;border-radius:8px}
.tabbar a svg{width:22px;height:22px;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.tabbar a[aria-current]{color:var(--c)}.tabbar a.q{background:var(--w);color:var(--k)}
body{padding-bottom:calc(74px + env(safe-area-inset-bottom))}.preview{bottom:calc(90px + env(safe-area-inset-bottom))}
.index .head,.venues .head,.deliver,.split2{grid-template-columns:1fr}.steps{grid-template-columns:1fr}
.steps>div{border-right:0;border-bottom:1px solid var(--g3)}.venues .grid{columns:1}
.frame{--h:clamp(240px,44vh,380px)}.side{position:relative;top:0}form.book{grid-template-columns:1fr}
.hero .photo{height:50svh;min-height:300px}.hero .copy{padding:28px var(--pad) 44px}.mega{font-size:min(clamp(30px,10.4vw,64px),calc((100vw - 100px) / 9.9))}
.hero .first{font-size:17px;margin-top:18px}.hero .lede{font-size:16px}.hero .row{margin-top:16px;gap:18px}
.vf i{width:28px;height:28px}.list a{grid-template-columns:44px 1fr auto}
.cover .grid{columns:2;gap:10px}.cover figure{margin-bottom:10px}.contact .hand{grid-template-columns:1fr}footer .foot{grid-template-columns:1fr;gap:28px}}
@media (max-width:360px){.top .tel span{display:none}}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}.mega span em{transform:none}.rv{opacity:1;transform:none}.hero canvas.web{display:none}}
"""

JS = r"""
(()=>{document.documentElement.classList.add('js');const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;const fine=matchMedia('(pointer: fine)').matches;
const top=document.querySelector('.top');const onScroll=()=>top&&top.classList.toggle('solid',scrollY>40);addEventListener('scroll',onScroll,{passive:true});onScroll();
// reveal
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.14});
document.querySelectorAll('.rv').forEach(el=>io.observe(el));
// cursor
const cur=document.querySelector('.cursor');
if(cur&&fine){addEventListener('mousemove',e=>{cur.classList.add('live');cur.style.transform='translate('+e.clientX+'px,'+e.clientY+'px)'});
document.querySelectorAll('a,button,.chips label').forEach(a=>{a.addEventListener('mouseenter',()=>cur.classList.add('big'));a.addEventListener('mouseleave',()=>cur.classList.remove('big'))})}
// the magnetic web over the hero (Chris, 2026-10-11): a drifting mesh of points and lines in the brand cyan that
// the pointer pulls toward itself; still under reduced motion, asleep while the hero is off screen or the tab hidden
const web=document.querySelector('.hero canvas.web');
if(web&&!reduce){const ctx=web.getContext('2d'),hero=web.parentElement;let W=0,H=0,pts=[],live=true,raf=0,done=false;const ptr={x:-1e4,y:-1e4,on:false};
const make=()=>{const r=hero.getBoundingClientRect(),dpr=Math.min(2,devicePixelRatio||1);W=r.width;H=r.height;web.width=W*dpr;web.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
const n=Math.round(Math.min(150,Math.max(50,W*H/13000)));pts=Array.from({length:n},()=>({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.35,vy:(Math.random()-.5)*.35,ox:0,oy:0,ovx:0,ovy:0}))};
const step=()=>{raf=0;if(!live)return;ctx.clearRect(0,0,W,H);const R=200,L=130;
for(const p of pts){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;
const dx=ptr.x-(p.x+p.ox),dy=ptr.y-(p.y+p.oy),d=Math.hypot(dx,dy);if(ptr.on&&d<R&&d>1){const f=(1-d/R)*1.1;p.ovx+=dx/d*f;p.ovy+=dy/d*f}
p.ovx-=p.ox*.03;p.ovy-=p.oy*.03;p.ovx*=.86;p.ovy*=.86;p.ox+=p.ovx;p.oy+=p.ovy}
ctx.lineWidth=1;for(let i=0;i<pts.length;i++){const a=pts[i],ax=a.x+a.ox,ay=a.y+a.oy;for(let j=i+1;j<pts.length;j++){const b=pts[j],bx=b.x+b.ox,by=b.y+b.oy;const dx=ax-bx,dy=ay-by;
if(dx>L||dx<-L||dy>L||dy<-L)continue;const d=Math.hypot(dx,dy);if(d>L)continue;ctx.strokeStyle='rgba(0,225,255,'+(.32*(1-d/L)).toFixed(3)+')';ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke()}}
ctx.fillStyle='rgba(0,225,255,.8)';for(const p of pts){ctx.beginPath();ctx.arc(p.x+p.ox,p.y+p.oy,1.5,0,6.2832);ctx.fill()}raf=requestAnimationFrame(step)};
const go=()=>{if(!raf&&live)raf=requestAnimationFrame(step)};const at=(cx,cy)=>{const r=hero.getBoundingClientRect();ptr.x=cx-r.left;ptr.y=cy-r.top;ptr.on=true};
make();addEventListener('resize',make);hero.addEventListener('mousemove',e=>at(e.clientX,e.clientY),{passive:true});hero.addEventListener('mouseleave',()=>{ptr.on=false});
hero.addEventListener('touchmove',e=>at(e.touches[0].clientX,e.touches[0].clientY),{passive:true});hero.addEventListener('touchend',()=>{ptr.on=false});
new IntersectionObserver(es=>{live=!done&&es[0].isIntersecting&&!document.hidden;go()}).observe(hero);document.addEventListener('visibilitychange',()=>{live=!done&&!document.hidden;go()});go();
// a reveal, then stillness (2026-10-12): the web plays for six seconds and fades, so the photograph and the words stand alone
setTimeout(()=>{web.style.transition='opacity 1.6s ease';web.style.opacity='0';setTimeout(()=>{done=true;live=false},1700)},6000)}
// no picture follows the pointer (Chris, 2026-10-14: "It just follows my mouse (that picture)"); the cursor ring is the one thing that does
// the work strip rolls on its own (Chris, 2026-10-14: "auto scrolling the gallery the entire time at a semi slow pace"): a native
// sideways strip with the frames doubled so the loop is seamless; it pauses under the pointer, a finger or keyboard focus, the arrows
// move it one frame, it stays still under reduced motion, and the page's own scrolling never moves it sideways
const roll=document.querySelector('.reel .track');
if(roll){const SPEED=24;let over=false,touch=false,focus=false,last=0,raf=0,hold=0,pos=roll.scrollLeft;
// the copies exist only for the loop (Chris, 2026-10-14: "the website gallery has duplicate images"): when the photos
// themselves fit the screen the copies would only read as repeats, so they go and the strip stands still
const own=[...roll.querySelectorAll('.frame:not([aria-hidden])')],lastOwn=own[own.length-1];
const fits=!lastOwn||lastOwn.offsetLeft+lastOwn.offsetWidth<=roll.clientWidth;
if(fits)roll.querySelectorAll('.frame[aria-hidden]').forEach(c=>c.remove());
// one period of the loop is the distance from the first frame to its copy (the frames are doubled)
const period=()=>{const f=roll.querySelectorAll('.frame');return f.length>1?f[f.length/2].offsetLeft-f[0].offsetLeft:0};
// a float of our own: scrollLeft rounds to whole pixels, so a fraction of a pixel added to it every frame adds nothing;
// a swipe or an arrow moves the strip itself, and the roll picks up from wherever it landed once the move is over (hold)
const step=t=>{raf=0;if(last){const dt=Math.min(64,t-last);if(!over&&!touch&&!focus&&!document.hidden&&t>hold&&period()>0){
if(Math.abs(roll.scrollLeft-pos)>1)pos=roll.scrollLeft;pos+=SPEED*dt/1000;if(pos>=period())pos-=period();roll.scrollLeft=pos}}last=t;raf=requestAnimationFrame(step)};
roll.addEventListener('pointerenter',()=>{over=true},{passive:true});roll.addEventListener('pointerleave',()=>{over=false},{passive:true});
roll.addEventListener('touchstart',()=>{touch=true},{passive:true});['touchend','touchcancel'].forEach(ev=>roll.addEventListener(ev,()=>{touch=false;hold=performance.now()+1200},{passive:true}));
roll.addEventListener('focusin',()=>{focus=true});roll.addEventListener('focusout',()=>{focus=false});
const width=()=>{const x=roll.scrollLeft;for(const f of roll.querySelectorAll('.frame')){if(f.offsetLeft+f.offsetWidth>x+1)return f.offsetWidth+18}return roll.clientWidth*.8};
document.querySelectorAll('.reel .arrows button').forEach(b=>b.addEventListener('click',()=>{hold=performance.now()+900;roll.scrollBy({left:(b.dataset.dir==='prev'?-1:1)*width(),behavior:'smooth'})}));
if(!reduce&&!fits)raf=requestAnimationFrame(step)}
// parallax
const par=[...document.querySelectorAll('[data-speed]')];
const move=()=>par.forEach(el=>{const r=el.parentElement.getBoundingClientRect();const d=(r.top+r.height/2-innerHeight/2)*parseFloat(el.dataset.speed);el.style.transform='translateY('+Math.max(-24,Math.min(24,d))+'px)'});
if(par.length&&!reduce){addEventListener('scroll',move,{passive:true});move()}
})();
"""


ICONS = {
    "work": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M3 16l5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1.5"/></svg>',
    "about": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>',
    "contact": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M3 7l9 6 9-6"/></svg>',
    "quote": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    "phone": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
}


def tel_href(phone: str) -> str:
    """The tappable form of the number: digits and a leading plus only. The live site of 2026-10-14 carried
    tel:(301)523-0841, the number as typed on the Keys page with its spaces removed; a dialer wants tel:3015230841."""
    import re
    return "tel:" + re.sub(r"(?!^\+)[^0-9]", "", phone.strip())


def _current(href: str, path: str) -> str:
    """aria-current on the link of the page you are on: a section link counts for the home page, and the Coverage
    link counts on every coverage page under it (2026-10-14)."""
    page = href.split("#")[0] or "/"
    if href.startswith("/#") and path != "/":
        return ""
    return ' aria-current="page"' if page == path or (page != "/" and path.startswith(page)) else ""


def shell(*, title: str, description: str, body: str, mark_svg: str, brand: str, legal: str, email: str,
          preview: bool, canonical: str, jsonld: str = "", og_image: str = "",
          sections: tuple = ("work", "venues"), verification: str = "", path: str = "/", phone: str = "",
          socials: tuple = (), coverage: tuple = (), area_line: str = "", noindex: bool = False,
          preload: str = "") -> str:
    """One shell for every page (2026-10-14: the three sizes). `sections`: the photo sections the home page has
    (a site built before any photo is cleared has none, so Work is left out). `verification`: the Google Search
    Console tag's content value. `path`: this page's path, for aria-current. `phone`: shown tappable when set.
    `socials`: (label, url) pairs for the footer and the business block. `coverage`: (key, label) pairs for the
    footer. `noindex`: the thank-you and not-found pages, never listed. `preload`: the hero's srcset, preloaded."""
    work = "/#work" if "work" in sections else "/coverage/"
    # the menu in words: Work only while the home page has the strip (a site built before any photo is cleared has none;
    # the footer and the phone's bar send Work to the coverage pages instead, so the word is never a dead link)
    links = ([(work, "Work")] if "work" in sections else []) + [("/coverage/", "Coverage"), ("/about/", "About"),
                                                                 ("/availability/", "Availability"), ("/contact/", "Contact")]
    nav = "".join(f'<a href="{h}"{_current(h, path)}>{label}</a>' for h, label in links)
    tabs = [(work, "work", "Work", ""), ("/about/", "about", "About", ""), ("/contact/", "contact", "Contact", ""), ("/book/", "quote", "Quote", " q")]
    tabbar = "".join(f'<a href="{h}" class="{icon}{cls}"{_current(h, path)}>{ICONS[icon]}<span>{label}</span></a>' for h, icon, label, cls in tabs)
    tel = (f'<a class="tel mono" href="{tel_href(phone)}" aria-label="Call {phone}">{ICONS["phone"]}<span>{phone}</span></a>'
           if phone else "")
    stamp = '<div class="preview mono">Preview, not live</div>' if preview else ""
    robots = '<meta name="robots" content="noindex,nofollow">' if preview or noindex else ""
    canon = "" if noindex else f'<link rel="canonical" href="{canonical}"><meta property="og:url" content="{canonical}">'
    og = (f'<meta property="og:image" content="{og_image}"><meta name="twitter:card" content="summary_large_image">'
          f'<meta name="twitter:image" content="{og_image}">') if og_image else '<meta name="twitter:card" content="summary">'
    verify = f'<meta name="google-site-verification" content="{verification}">' if verification and not preview else ""
    pre = f'<link rel="preload" as="image" imagesrcset="{preload}" imagesizes="100vw">' if preload else ""
    cover_links = "".join(f'<li><a href="/coverage/{k}/">{label}</a></li>' for k, label in coverage)
    social_links = "".join(f'<li><a href="{url}" rel="me noopener">{label}</a></li>' for label, url in socials)
    phone_li = f'<li><a href="{tel_href(phone)}">{phone}</a></li>' if phone else ""
    from datetime import date
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{title}</title>
<meta name="description" content="{description}">{canon}{robots}{verify}
<meta property="og:title" content="{title}"><meta property="og:description" content="{description}"><meta property="og:type" content="website"><meta property="og:site_name" content="{brand}">{og}
<meta name="twitter:title" content="{title}"><meta name="twitter:description" content="{description}">
<meta name="theme-color" content="#0A0A0B"><link rel="icon" href="/assets/mark.svg" type="image/svg+xml">{pre}
<link rel="stylesheet" href="/assets/site.css"><script>document.documentElement.classList.add("js")</script>{jsonld}
</head><body><div class="grain" aria-hidden="true"></div><div class="cursor" aria-hidden="true"></div>
<header class="top"><a class="logo" href="/" aria-label="{brand} home">{mark_svg}</a>
<nav class="mono" aria-label="Pages">{nav}</nav>{tel}
<a class="btn" href="/book/"><span class="long">Request a </span>quote <span class="arr">&#8599;</span></a></header>
<main>{body}</main>
<footer><div class="big" aria-hidden="true">{brand}</div><div class="foot">
<div><h4>{brand}</h4><p class="about">Event and convention photography by two brothers, more than thirty years each. {area_line}</p></div>
<div><h4>Coverage</h4><ul>{cover_links}</ul></div>
<div><h4>Pages</h4><ul><li><a href="{work}">Work</a></li><li><a href="/about/">About</a></li><li><a href="/availability/">Availability</a></li><li><a href="/contact/">Contact</a></li><li><a href="/book/">Request a quote</a></li><li><a href="/privacy/">Privacy and photo removal</a></li></ul></div>
<div><h4>Contact</h4><ul><li><a href="mailto:{email}">{email}</a></li>{phone_li}{social_links}</ul></div></div>
<div class="legal mono"><span>&#169; {date.today().year} {legal}. {brand} is a brand of {legal}.</span><span>Washington, DC</span></div></footer>
<nav class="tabbar" aria-label="Pages">{tabbar}</nav>
{stamp}<script src="/assets/site.js" defer></script></body></html>"""
