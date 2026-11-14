/* tacit: drawing helpers. One grid, three marks (dot, dash, plus). Everything drawn on a canvas goes through glyph(). */
(function(){
'use strict';
var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
var TICK = 110; /* one grid step every 110 ms, about nine frames a second */

function hash(s){ var h=2166136261>>>0; for(var i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619); } return h>>>0; }
function rng(a){ return function(){ a|=0; a=a+0x6D2B79F5|0; var t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }
function fit(cv){ var r=cv.getBoundingClientRect(), d=Math.min(2,window.devicePixelRatio||1);
  cv.width=Math.max(1,Math.round(r.width*d)); cv.height=Math.max(1,Math.round(r.height*d));
  var c=cv.getContext('2d'); c.setTransform(d,0,0,d,0,0); return {W:r.width,H:r.height,ctx:c}; }

/* one mark on the grid: v<0 upright dash · <0.3 dot · <0.55 dash · <0.9 plus · else bold plus */
function glyph(ctx,s){
  var a=Math.max(1,Math.round(s*0.42)), w=Math.max(1,Math.round(s*0.16)), w2=w*2, d=Math.max(1,w+1);
  return function(X,Y,v){
    if(v<0){ ctx.fillRect(X-w/2,Y-a,w,a*2); }
    else if(v<0.3){ ctx.fillRect(X-d/2,Y-d/2,d,d); }
    else if(v<0.55){ ctx.fillRect(X-a,Y-w/2,a*2,w); }
    else if(v<0.9){ ctx.fillRect(X-a,Y-w/2,a*2,w); ctx.fillRect(X-w/2,Y-a,w,a*2); }
    else { ctx.fillRect(X-a,Y-w2/2,a*2,w2); ctx.fillRect(X-w2/2,Y-a,w2,a*2); }
  };
}
/* the drawing colour is the canvas's CSS color; the "passing" colour is the CSS variable --lit */
function colors(cv){ var cs=getComputedStyle(cv); return { col:cs.color, lit:(cs.getPropertyValue('--lit')||'').trim()||cs.color }; }
/* a skill in transit: same marks, warm colour, soft glow */
function drawHot(ctx,put,hot,lit){ if(!hot.length) return; ctx.save(); ctx.fillStyle=lit; ctx.shadowColor=lit; ctx.shadowBlur=9;
  for(var i=0;i<hot.length;i+=3) put(hot[i],hot[i+1],hot[i+2]); ctx.restore(); }
function snap(v,s){ return Math.round((v-s/2)/s)*s+s/2; }
/* a ready canvas: cleared, sized, with put(x,y,v) */
function pen(cv,s){ var S=fit(cv), C=colors(cv); S.ctx.clearRect(0,0,S.W,S.H); S.ctx.fillStyle=C.col;
  return { W:S.W, H:S.H, ctx:S.ctx, put:glyph(S.ctx,s), col:C.col, lit:C.lit, s:s }; }
/* a person: a ring of plus signs with a bold plus in the middle. Pass an array as hot to collect the marks instead of drawing them. */
function ring(put,x,y,rho,s,hot){ var span=Math.ceil(rho/s)+1;
  for(var yy=-span;yy<=span;yy++) for(var xx=-span;xx<=span;xx++){ var dd=Math.sqrt(xx*xx+yy*yy)*s, v;
    if(xx===0&&yy===0) v=1; else if(Math.abs(dd-rho)<s*0.55) v=0.7; else continue;
    if(hot) hot.push(Math.round(x+xx*s),Math.round(y+yy*s),v); else put(Math.round(x+xx*s),Math.round(y+yy*s),v); } }

/* ---- example data: people and who passed which skill to whom ---- */
var ALL=['Maya','You','Kai','Lena','Omar','Ines','Theo','Noor','Sam','Zoe','Ben','Ravi'];
var WT=[1,.5,.3,.8,.55,.45,.3,.75,.25,.6,.35,.4];           /* how much each person has given */
var SK=['Open with the number','Say no kindly','Cut scope early','Name the risk'];
/* link = [from, to, skill, whose skill it is] */
function dataFor(K){
  var people=[], links, i;
  for(i=0;i<K;i++) people.push({n:ALL[i],w:WT[i],id:i});
  if(K<=3) links=[[0,1,0,0],[1,2,0,0],[2,0,1,2]];
  else { links=[[0,1,0,0],[1,2,0,0],[3,1,2,3],[4,3,1,4],[3,0,3,3],[0,4,0,0],[1,4,2,3]].filter(function(l){ return l[0]<K&&l[1]<K; });
    var r=rng(hash('links'+K));
    for(i=5;i<K;i++){ var a=(r()*i)|0, b=(r()*K)|0; if(b===i) b=(i+1)%K; links.push([a,i,(r()*4)|0,a]); links.push([i,b,(r()*4)|0,i]); }
    if(K>5) links.sort(function(){ return r()-0.5; }); }
  return {people:people,links:links,skills:SK};
}
function Flow(get){ var k=-1,t=1e9, f={cur:null,u:0,fresh:false,hit:false,
  step:function(dur,gap){ var L=get(); f.fresh=f.hit=false; t++; if(t>=dur+gap||!f.cur){ t=0; k=(k+1)%L.length; f.cur=L[k]; f.fresh=true; } f.u=Math.min(1,t/dur); if(t===dur) f.hit=true; return f; },
  reset:function(){ k=-1; t=1e9; f.cur=null; f.u=0; } }; return f; }
function Names(host){ var box=host&&host.querySelector('.tc-names'), els=[];
  return { set:function(list){ if(!box) return; box.textContent=''; els=list.map(function(l){ var b=document.createElement('b'); b.className='tc-nm'; b.textContent=l.t;
        b.style.left=Math.round(l.x)+'px'; b.style.top=Math.round(l.y)+'px'; b.style.transform='translate('+(l.ax||'-50%')+','+(l.ay||'-50%')+')'; box.appendChild(b); return b; });
      host.classList.toggle('many',list.length>7); },
    move:function(i,x,y){ var e=els[i]; if(e){ e.style.left=Math.round(x)+'px'; e.style.top=Math.round(y)+'px'; } },
    say:function(i){ for(var j=0;j<els.length;j++) els[j].classList.toggle('say',j===i); },
    got:function(i){ var e=els[i]; if(!e) return; e.classList.remove('got'); void e.offsetWidth; e.classList.add('got'); } }; }
/* the chip that names who passed what */
function Ticker(host){ var el=host&&host.querySelector('.tc-chip');
  return function(D,l){ if(!el) return; var P=D.people, S=D.skills||SK;
    el.textContent='';
    function add(tag,text){ var n=document.createElement(tag); n.textContent=text; el.appendChild(n); }
    add('b',P[l[0]].n); add('i','→'); add('b',P[l[1]].n); add('em',S[l[2]]); if(l[3]!==l[0]) add('small','from '+P[l[3]].n);
    el.classList.remove('in'); void el.offsetWidth; el.classList.add('in'); }; }
/* shared timing: start a pass, light the giver's name, pulse the receiver's */
function beat(m,dur,gap){ var fl=m.fl; fl.step(dur,gap);
  if(fl.fresh){ m.names.say(fl.cur[0]); m.tk(m.D,fl.cur); if(m.onFresh) m.onFresh(fl.cur); }
  if(fl.hit){ m.names.say(-1); if(m.onHit) m.onHit(fl.cur); } }

/* ============ the network: people gather in loose groups and walk between them ============
   field(canvas, stageElement, {K, cell}) · options: still (a quiet watermark), data {people,links,skills},
   groups [three words], masks [bit 0 first group · 1 second · 2 third], gx / gy (where the three groups gather, 0..1),
   left / right / top / bot (the area people stay in: a share of the stage when 1 or less, else px),
   onStart(link) and onGot(link) (a pass begins · the learner has the skill), dur / gap / wait (ticks),
   halo (a soft dark halo under each ring, for rings that sit on the peach glow) */
function field(cv,host,o){
  var S,n=0,K,P=[],F=[],GL=[],pulse=[],got=false,labs=host&&host.querySelector('.tc-labs'), m={D:o.data||dataFor(o.K),names:Names(host),tk:Ticker(host)};
  var GN=o.groups||['founders','creative professionals','engineers'], MK=o.masks||[1,2,4,5,3,1,6,1,4,2,3,4];
  m.fl=Flow(function(){ return m.D.links; });
  m.onFresh=function(l){ got=false; if(o.onStart) o.onStart(l); };
  function part(v,total,def){ return v==null?def:(v<=1?v*total:v); }
  function layout(){ S=fit(cv); var W=S.W,H=S.H,s=o.cell,lab=[],i,j,b,it; K=m.D.people.length; P=[]; pulse=[]; got=false;
    var gx=o.gx||(o.still?[0.27,0.5,0.74]:[0.25,0.52,0.78]), gy=o.gy||(o.still?[0.32,0.72,0.3]:[0.43,0.64,0.4]);
    var GC=[{x:W*gx[0],y:H*gy[0]},{x:W*gx[1],y:H*gy[1]},{x:W*gx[2],y:H*gy[2]}];
    var sp=Math.min(W*0.13,H*0.2)*(o.spread||1), r=rng(hash('field'+K)), seen=[0,0,0];
    var mx=o.still?s*4:(o.side||70), top=o.still?s*4:part(o.top,H,96), bot=o.still?s*4:part(o.bot,H,118);
    var x0=o.still?mx:part(o.left,W,mx), x1=o.still?W-mx:part(o.right,W,W-mx);
    for(i=0;i<K;i++){ var mk=MK[i], tx=0, ty=0, c=0; for(b=0;b<3;b++) if(mk>>b&1){ tx+=GC[b].x; ty+=GC[b].y; c++; } tx/=c; ty/=c;
      var gi=Math.round(Math.log(mk)/Math.LN2), first=(c===1&&!seen[gi]); if(c===1) seen[gi]=1;
      var ang=r()*6.2832, rad=(first?0.08:c>1?0.2:0.45+0.5*r())*sp;
      P.push({hx:tx+Math.cos(ang)*rad,hy:ty+Math.sin(ang)*rad,tx:tx,ty:ty,mk:mk,rho:s*(o.still?1.6:1.9+1.2*m.D.people[i].w),
        x:x0+r()*(x1-x0),y:top+r()*(H-top-bot)}); pulse.push(0); }
    for(it=0;it<90;it++){
      for(i=0;i<K;i++) for(j=i+1;j<K;j++){ var dx=P[j].hx-P[i].hx, dy=P[j].hy-P[i].hy, d=Math.sqrt(dx*dx+dy*dy)||1, need=P[i].rho+P[j].rho+s*(o.still?3:8);
        if(d<need){ var push=(need-d)/2; dx/=d; dy/=d; P[i].hx-=dx*push; P[i].hy-=dy*push; P[j].hx+=dx*push; P[j].hy+=dy*push; } }
      for(i=0;i<K;i++){ var q=P[i]; q.hx+=(q.tx-q.hx)*0.03; q.hy+=(q.ty-q.hy)*0.03; q.hx=Math.max(x0,Math.min(x1,q.hx)); q.hy=Math.max(top,Math.min(H-bot,q.hy)); } }
    for(i=0;i<K;i++){ if(o.still){ P[i].x=P[i].hx; P[i].y=P[i].hy; } P[i].sx=snap(P[i].x,s); P[i].sy=snap(P[i].y,s);
      lab.push({t:m.D.people[i].n,x:P[i].sx,y:P[i].sy+P[i].rho+s*0.3,ax:'-50%',ay:'0'}); }
    /* the word for a group sits above where its people gather; there is no outline */
    GL=[]; if(labs) labs.textContent='';
    for(b=0;b<3;b++){ var sx=0,cnt=0,ymin=1e9,ymax=-1e9; for(i=0;i<K;i++) if(P[i].mk>>b&1){ if(P[i].mk===(1<<b)){ sx+=P[i].hx; cnt++; } if(P[i].hy-P[i].rho<ymin) ymin=P[i].hy-P[i].rho; if(P[i].hy+P[i].rho>ymax) ymax=P[i].hy+P[i].rho; }
      if(!cnt) continue; GL.push({x:sx/cnt,y:GC[b].y});
      if(labs && GN[b]){ var el=document.createElement('i'), low=GC[b].y>H*0.5; el.className='tc-co'; el.textContent=GN[b]; el.style.left=Math.round(Math.max(120,Math.min(W-120,low?GC[b].x:sx/cnt)))+'px';
        el.style.top=Math.round(low?Math.min(H-104,ymax+44):Math.max(64,ymin-14))+'px'; el.style.transform='translate(-50%,'+(low?'0':'-100%')+')'; labs.appendChild(el); } }
    /* grid cells; g = how much a cell belongs to a group's home ground (soft, no edge) */
    F=[]; var x, y;
    for(y=s/2;y<H;y+=s) for(x=s/2;x<W;x+=s){ var f=0;
      for(b=0;b<GL.length;b++){ var gx=x-GL[b].x, gy=y-GL[b].y; f+=0.4*Math.exp(-(gx*gx+gy*gy)/(2*sp*sp)); }
      F.push({x:x,y:y,g:f,k:(Math.round((x-s/2)/s)+Math.round((y-s/2)/s))&1}); }
    if(!o.still) m.names.set(lab); }
  /* people drift a little at home; the one who is learning walks over to the one who explains, then walks back */
  function step(){ var s=o.cell, a=-1,b=-1,u=0,i; if(m.fl.cur){ a=m.fl.cur[0]; b=m.fl.cur[1]; u=m.fl.u; }
    for(i=0;i<K;i++){ var p=P[i], tx=p.hx+Math.sin(n*0.05+i*1.7)*s*0.8, ty=p.hy+Math.cos(n*0.04+i*2.3)*s*0.8;
      if(i===b && u>0 && u<0.72){ var A=P[a], dx=p.hx-A.hx, dy=p.hy-A.hy, d=Math.sqrt(dx*dx+dy*dy)||1, gp=A.rho+p.rho+s*2; tx=A.x+dx/d*gp; ty=A.y+dy/d*gp;
        var ex=p.x-A.x, ey=p.y-A.y; if(!got && Math.sqrt(ex*ex+ey*ey)<gp*1.3){ got=true; pulse[b]=1; m.names.got(b); if(o.onGot) o.onGot(m.fl.cur); } }
      p.x+=(tx-p.x)*0.17; p.y+=(ty-p.y)*0.17; p.sx=snap(p.x,s); p.sy=snap(p.y,s);
      m.names.move(i,p.sx,p.sy+p.rho+s*0.3); } }
  function draw(){
    var W=S.W,H=S.H,ctx=S.ctx,s=o.cell,put=glyph(ctx,s),Co=colors(cv),hot=[],i,q;
    var g=o.still?1:Math.min(1,0.08+n*0.05), a=-1,b=-1,u=0; if(m.fl.cur){ a=m.fl.cur[0]; b=m.fl.cur[1]; u=m.fl.u; }
    var A=a>=0?P[a]:null, B=b>=0?P[b]:null, near=false, gp2=0;
    if(A&&B){ var ddx=B.sx-A.sx, ddy=B.sy-A.sy; gp2=A.rho+B.rho+s*2; near=(ddx*ddx+ddy*ddy<gp2*gp2*1.8) && u<0.8; gp2=gp2*gp2*0.75; }
    ctx.clearRect(0,0,W,H); ctx.fillStyle=Co.col;
    var far=o.still?0:0.3, RM=Math.sqrt(W*W+H*H)/2*g, sg=s*5.2, inv=1/(2*sg*sg), lim=sg*sg*10, rr=[];
    for(i=0;i<K;i++) rr.push((P[i].rho+s*0.9)*(P[i].rho+s*0.9));
    for(q=0;q<F.length;q++){ var c=F[q], dx=c.x-W/2, dy=c.y-H/2; if(g<1 && dx*dx+dy*dy>RM*RM) continue;
      var f=c.g, skip=false, dA=1e9, dB=1e9;
      for(i=0;i<K;i++){ var ex=c.x-P[i].sx, ey=c.y-P[i].sy, d2=ex*ex+ey*ey; if(d2<rr[i]){ skip=true; break; } if(d2<lim) f+=Math.exp(-d2*inv); if(i===a) dA=d2; else if(i===b) dB=d2; }
      if(skip) continue;
      var X=Math.round(c.x), Y=Math.round(c.y);
      if(near && dA<gp2 && dB<gp2){ hot.push(X,Y,0.7); continue; }                      /* the spot between them lights up while the skill passes */
      var wob=Math.sin(c.x*0.045+c.y*0.03-n*0.2);
      if(f>1.05){ if(wob>0.9) continue; ctx.globalAlpha=0.95; put(X,Y,0.4); }
      else if(f>0.32){ if(wob>0.86) continue; ctx.globalAlpha=0.85; put(X,Y,0.12); }
      else { if(c.k||!far) continue; ctx.globalAlpha=far; put(X,Y,0.12); } }
    ctx.globalAlpha=1;
    if(o.halo){ ctx.shadowColor='rgba(35,25,90,.7)'; ctx.shadowBlur=6; }
    for(i=0;i<K;i++){
      var p=P[i], rho=p.rho*(1+0.2*pulse[i]), isHot=(i===a&&near)||(i===b&&got)||pulse[i]>0.3;
      ring(put,p.sx,p.sy,rho,s,isHot?hot:null); }
    if(o.halo){ ctx.shadowBlur=0; ctx.shadowColor='transparent'; }
    drawHot(ctx,put,hot,Co.lit);
  }
  layout(); draw();
  return { warm:o.warm||60, tick:function(){ n++; if(!o.still){ if(n>(o.wait||30)) beat(m,o.dur||44,o.gap||14); step(); } for(var i=0;i<pulse.length;i++) pulse[i]=Math.max(0,pulse[i]-0.1); draw(); },
    resize:function(){ layout(); draw(); }, set:function(k){ m.D=dataFor(k); m.fl.reset(); n=0; layout(); draw(); } };
}

/* ---- the plus-sign flower (status: to confirm; liked in the phone player, rejected for the network) ---- */
function bloom(cv,o){
  var S, n=0, r0=rng(hash(o.seed)), k=o.petals||(5+((r0()*3)|0)), rot=(o.rot!=null?o.rot:r0()*6.283);
  function size(){ S=fit(cv); }
  function draw(){
    var W=S.W,H=S.H,ctx=S.ctx,s=o.cell, g=Math.min(1,0.1+n*0.07), t=(o.still&&g>=1)?0:n;
    ctx.clearRect(0,0,W,H); ctx.fillStyle=getComputedStyle(cv).color;
    var cx=W*o.cx, cy=H*o.cy, R=Math.min(W,H)*o.r, a=Math.round(s*0.42), w=Math.max(1,Math.round(s*0.16)), w2=w*2;
    for(var y=s/2;y<H;y+=s) for(var x=s/2;x<W;x+=s){
      var dx=x-cx, dy=y-cy, r=Math.sqrt(dx*dx+dy*dy), v=0;
      if(r<R*1.05){
        var th=Math.atan2(dy,dx)+rot;
        var outer=R*g*(0.46+0.54*Math.pow(Math.abs(Math.cos(k*th/2)),0.5));
        if(r<outer){
          var q=r/outer; v = q>0.9 ? 1 : 0.24+0.5*(0.5+0.5*Math.sin(q*12-t*0.5+th*2));
          var inner=R*g*0.54*(0.5+0.5*Math.pow(Math.abs(Math.cos(k*th/2+1.5708)),0.5));
          if(r<inner){ var qi=r/inner; v = qi>0.86 ? 1 : 0.5+0.3*(0.5+0.5*Math.sin(qi*8+t*0.4)); }
          if(r<R*g*0.14) v=0.12;
        }
      }
      if(!v) continue;
      var X=Math.round(x), Y=Math.round(y);
      if(v<0.3){ ctx.fillRect(X-w/2,Y-w/2,w,w); }
      else if(v<0.55){ ctx.fillRect(X-a,Y-w/2,a*2,w); }
      else if(v<0.9){ ctx.fillRect(X-a,Y-w/2,a*2,w); ctx.fillRect(X-w/2,Y-a,w,a*2); }
      else { ctx.fillRect(X-a,Y-w2/2,a*2,w2); ctx.fillRect(X-w2/2,Y-a,w2,a*2); }
    }
  }
  size(); draw();
  return { warm:16, tick:function(){ if(o.still && n>16) return; n++; draw(); }, reset:function(){ n=0; draw(); }, resize:function(){ size(); draw(); },
    full:function(){ n=20; draw(); } };
}
/* ---- the one-minute player on the skill card: the drawing grows while the minute plays ---- */
function minute(root){
  var wave=root.querySelector('.tc-wave'), cur=root.querySelector('.tc-time span'), cv=root.querySelector('.tc-player canvas'), r=rng(hash('minute')), n=0, N=34;
  for(var i=0;i<N;i++){ var b=document.createElement('i'); b.style.setProperty('--h',Math.round(22+r()*78)+'%'); wave.appendChild(b); }
  var bars=wave.children, bl=bloom(cv,{seed:'Open with the number, not the story|Maya',petals:6,rot:0.3,cell:6,cx:0.5,cy:0.5,r:0.44});
  function show(){ var f=Math.min(1,n/16), on=Math.round(N*f), sec=Math.round(60*f); for(var i=0;i<N;i++) bars[i].className=i<on?'on':''; if(cur) cur.textContent=(sec>=60?'1:00':'0:'+(sec<10?'0':'')+sec); }
  show();
  return { warm:16, tick:function(){ n=(n+1)%21; if(n===0) bl.reset(); else bl.tick(); show(); }, reset:function(){ n=0; bl.reset(); show(); }, resize:function(){ bl.resize(); } };
}

/* run a drawing: m.tick() every ms (default one grid step), paused off screen, settled frame when motion is reduced */
function run(m,ms,el){ ms=ms||TICK; var last=0, vis=true, stopped=false, i, rt;
  function refit(){ clearTimeout(rt); rt=setTimeout(function(){ if(m.resize) m.resize(); },150); }
  window.addEventListener('resize',refit); window.addEventListener('load',refit);
  if(document.fonts && document.fonts.ready) document.fonts.ready.then(refit);
  if(reduce){ for(i=0;i<(m.warm||20);i++) m.tick(); return function(){}; }
  if(el && 'IntersectionObserver' in window){ new IntersectionObserver(function(es){ vis=es[es.length-1].isIntersecting; },{rootMargin:'150px'}).observe(el); }
  (function frame(now){ if(stopped) return; if(vis && now-last>=ms){ last=now; m.tick(); } requestAnimationFrame(frame); })(0);
  return function(){ stopped=true; };
}

window.Tacit = { TICK:TICK, reduce:reduce, hash:hash, rng:rng, fit:fit, glyph:glyph, colors:colors, drawHot:drawHot, snap:snap, pen:pen, ring:ring,
  dataFor:dataFor, field:field, bloom:bloom, minute:minute, run:run };
})();
