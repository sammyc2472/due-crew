// 3.9.1, room sounds (Sam's picks: made from noise only, a speaker on the
// chip, each person their own): brown noise, rain, fire and waves, made by
// Web Audio from noise. No sound files, no timers: what happens now and then
// (a drop, a crackle, a wave) is either drawn once into a buffer that loops
// (two loops of different lengths, so the pattern never comes round) or
// shaped by slow oscillators. A page that's hidden (Anki can hide the top bar
// while reviewing) slows its timers; these keep going because there are none.
// Fades in and out over 1.5 s, and a switch crossfades. It lives in the top
// bar's page (room_model.sound_js puts it there, once), which Anki keeps
// through review. window.dcSounds = {kinds, labels, play, stop, setVolume,
// playing, build}; build(ctx, kind, out) draws one sound into any context, an
// OfflineAudioContext too.
// Since Sam's "the background noises aren't the best": rain, fire and waves
// are recordings when the add-on has them (sounds/*.ogg, CC0: see
// sounds/CREDITS.md), each a seamless loop played sample-exact by an
// AudioBufferSourceNode; brown noise stays made, as brown noise is. Only the
// sound that's playing is decoded (a minute of stereo is ~23 MB as samples).
// A file that won't load or decode plays the made one instead.
(function () {
  if (window.dcSounds) { return; }  // once a page: a second copy couldn't stop the first's sound
  var FADE = 1.5;
  var KINDS = ["brown", "rain", "fire", "waves"];
  var LABELS = { brown: "Brown noise", rain: "Rain", fire: "Fire", waves: "Waves" };
  // each kind's own level, so all four sound about as loud at one volume
  var TRIM = { brown: 0.81, rain: 0.8, fire: 1.33, waves: 1.07 };

  // a seeded random, so a context's buffers are the same every time it's built
  function rng(seed) {
    var s = seed >>> 0;
    return function () {
      s = (s + 0x6D2B79F5) >>> 0;
      var t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // one stereo buffer of white noise per context (left and right apart),
  // played from different places in it with loops of different lengths
  function noise(ctx) {
    if (ctx.__dcNoise) { return ctx.__dcNoise; }
    var n = Math.round(ctx.sampleRate * 10.3), b = ctx.createBuffer(2, n, ctx.sampleRate);
    for (var c = 0; c < 2; c++) {
      var d = b.getChannelData(c), r = rng(c ? 7919 : 104729);
      for (var i = 0; i < n; i++) { d[i] = r() * 2 - 1; }
    }
    ctx.__dcNoise = b;
    return b;
  }
  function src(ctx, from, to, offset) {
    var s = ctx.createBufferSource(), b = noise(ctx);
    s.buffer = b; s.loop = true;
    s.loopStart = from * b.duration; s.loopEnd = to * b.duration;
    s.__at = s.loopStart + offset * (s.loopEnd - s.loopStart);
    return s;
  }
  // two loops of one noise, summed, each read a hair faster or slower as it
  // goes (a percent either way: no one hears it in noise), so neither loop
  // ever plays back the same twice
  function wide(ctx, nodes) {
    var g = ctx.createGain(); g.gain.value = Math.SQRT1_2;
    var a = src(ctx, 0, 1, 0), b = src(ctx, 0.08, 0.77, 0.4);
    lfo(ctx, nodes, 0.023, 0.012).connect(a.playbackRate);
    lfo(ctx, nodes, 0.031, 0.012).connect(b.playbackRate);
    a.connect(g); b.connect(g);
    nodes.push(a, b);
    return g;
  }
  // brown: white noise through a leaky integrator (an IIR filter: no loop
  // seam, as integrating a buffer would leave), then the rumble below 25 Hz out
  function brown(ctx, nodes, input) {
    var leak = 0.996, i = ctx.createIIRFilter([1 - leak], [1, -leak]);
    var hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 25; hp.Q.value = 0.5;
    var g = ctx.createGain(); g.gain.value = 4.2;
    (input || wide(ctx, nodes)).connect(i); i.connect(hp); hp.connect(g);
    return g;
  }
  function lfo(ctx, nodes, hz, depth, type) {
    var o = ctx.createOscillator(); o.type = type || "sine"; o.frequency.value = hz;
    var g = ctx.createGain(); g.gain.value = depth;
    o.connect(g); nodes.push(o);
    return g;
  }
  function filter(ctx, type, hz, q) {
    var f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = hz;
    if (q != null) { f.Q.value = q; }
    return f;
  }
  function peak(ctx, hz, q, db) { var f = filter(ctx, "peaking", hz, q); f.gain.value = db; return f; }
  function gain(ctx, v) { var g = ctx.createGain(); g.gain.value = v; return g; }
  function chain() {
    for (var i = 0; i < arguments.length - 1; i++) { arguments[i].connect(arguments[i + 1]); }
    return arguments[arguments.length - 1];
  }

  // a looped buffer of events (drops, crackles), drawn once: each(d, r, sr)
  // writes into the two channels at random places. Half the context's rate
  // (all of it is under 10 kHz), so a long loop stays small; read with a
  // little wander, so a loud one never comes round exactly in time
  function events(ctx, nodes, secs, seed, each) {
    var sr = 24000, n = Math.round(sr * secs), b = ctx.createBuffer(2, n, sr);
    each([b.getChannelData(0), b.getChannelData(1)], rng(seed), sr, n);
    var s = ctx.createBufferSource(); s.buffer = b; s.loop = true; s.__at = 0;
    lfo(ctx, nodes, 0.017 + (seed % 7) / 1000, 0.008).connect(s.playbackRate);
    nodes.push(s);
    return s;
  }
  // add one decaying sound at sample i: a ping (sine at hz) or a tick (noise)
  function strike(ch, r, sr, n, i, o) {
    var len = Math.min(Math.round(sr * o.decay * 6), Math.round(sr * 0.4));
    var pl = Math.cos((o.pan + 1) * Math.PI / 4), pr = Math.sin((o.pan + 1) * Math.PI / 4);
    var w = 2 * Math.PI * (o.hz || 0) / sr, k = 1 / (sr * o.decay), lp = 0, a = o.amp, att = Math.max(1, Math.round(sr * (o.attack || 0.0004)));
    var br = 1 - Math.pow(1 - (o.bright || 0.6), 48000 / sr);  // bright as at 48 kHz, whatever the rate
    for (var j = 0; j < len; j++) {
      var e = Math.exp(-j * k) * (j < att ? j / att : 1), v;
      if (o.hz) {
        v = Math.sin(w * j + (o.chirp ? o.chirp * j * j / sr / sr : 0));
      } else {
        lp += (r() * 2 - 1 - lp) * br; v = lp;
      }
      var at = (i + j) % n;  // wraps, so the loop has no seam
      ch[0][at] += v * e * a * pl;
      ch[1][at] += v * e * a * pr;
    }
  }

  var BUILD = {
    brown: function (ctx, nodes, out) {
      // a slow drift in its warmth, so it breathes a little
      var lp = filter(ctx, "lowpass", 900, 0.4);
      lfo(ctx, nodes, 0.021, 160).connect(lp.frequency);
      chain(brown(ctx, nodes), lp, out);
    },

    rain: function (ctx, nodes, out) {
      // the steady wash: mid and high noise, with a slow come and go
      var bed = chain(wide(ctx, nodes), filter(ctx, "highpass", 500, 0.5), filter(ctx, "lowpass", 7000, 0.5),
                      peak(ctx, 2600, 0.7, 4), gain(ctx, 0.075));
      var swell = gain(ctx, 1);
      lfo(ctx, nodes, 0.043, 0.18).connect(swell.gain);
      lfo(ctx, nodes, 0.011, 0.12).connect(swell.gain);
      bed.connect(swell);
      // far off: a soft low rumble
      var low = chain(brown(ctx, nodes), filter(ctx, "lowpass", 260, 0.5), gain(ctx, 0.5));
      // drops: many small ones everywhere, a few close plinks; two loops
      function drops(d, r, sr, n, perSec, close) {
        var t = 0;
        while (true) {
          t += -Math.log(1 - r()) / perSec;
          var i = Math.round(t * sr);
          if (i >= n) { break; }
          var near = r() < close, amp = Math.pow(r(), 2.2);
          strike(d, r, sr, n, i, near
            ? { hz: 900 + r() * 1700, decay: 0.012 + r() * 0.02, amp: 0.05 + amp * 0.18, pan: r() * 1.6 - 0.8, chirp: -900 * r() }
            : { decay: 0.0015 + r() * 0.004, amp: 0.03 + amp * 0.16, pan: r() * 2 - 1, bright: 0.35 + r() * 0.5 });
        }
      }
      var a = events(ctx, nodes, 29.3, 31, function (d, r, sr, n) { drops(d, r, sr, n, 45, 0.04); });
      var b = events(ctx, nodes, 41.9, 47, function (d, r, sr, n) { drops(d, r, sr, n, 28, 0.06); });
      var dl = chain(filter(ctx, "highpass", 700, 0.5), filter(ctx, "lowpass", 9000, 0.4), gain(ctx, 3.2));
      a.connect(dl); b.connect(dl);
      var sum = gain(ctx, 1);
      swell.connect(sum); low.connect(sum); dl.connect(sum);
      sum.connect(out);
    },

    fire: function (ctx, nodes, out) {
      // the body of the fire: warm low noise that flickers
      var body = chain(brown(ctx, nodes), filter(ctx, "lowpass", 380, 0.6), gain(ctx, 0.6));
      var flick = gain(ctx, 0.8);
      lfo(ctx, nodes, 0.31, 0.16).connect(flick.gain);
      lfo(ctx, nodes, 0.73, 0.09).connect(flick.gain);
      lfo(ctx, nodes, 0.053, 0.12).connect(flick.gain);
      body.connect(flick);
      // the flame's breath, higher and quieter
      var roar = chain(wide(ctx, nodes), filter(ctx, "bandpass", 700, 0.6), gain(ctx, 0.03));
      lfo(ctx, nodes, 0.41, 0.014).connect(roar.gain);
      // crackles: bursts of a few clicks, sparse; now and then a pop or a hiss
      function crackle(d, r, sr, n, perSec) {
        var t = 0.2;
        while (true) {
          t += -Math.log(1 - r()) / perSec;
          var i = Math.round(t * sr);
          if (i >= n) { break; }
          var pan = (r() * 2 - 1) * 0.45, roll = r();
          if (roll < 0.07) {           // a wood pop: low, round, louder
            strike(d, r, sr, n, i, { hz: 160 + r() * 260, decay: 0.012 + r() * 0.02, amp: 0.11 + r() * 0.09, pan: pan, chirp: -6000 });
            strike(d, r, sr, n, i, { decay: 0.003, amp: 0.12, pan: pan, bright: 0.9 });
          } else if (roll < 0.1) {     // sap: a short hiss
            var len = 0.25 + r() * 0.9;
            for (var k = 0; k < 18; k++) {
              strike(d, r, sr, n, i + Math.round((k / 18) * len * sr), { decay: len / 12, amp: 0.012 * Math.sin(Math.PI * k / 18), pan: pan, bright: 0.95 });
            }
          } else {                     // a crackle: 1 to 8 clicks close together
            var m = 1 + Math.floor(Math.pow(r(), 1.6) * 8), at = i, loud = 0.12 + Math.pow(r(), 1.5) * 0.3;
            for (var c = 0; c < m; c++) {
              strike(d, r, sr, n, at, { decay: 0.0003 + r() * 0.0012, amp: loud * (0.4 + r() * 0.6), pan: pan + (r() - 0.5) * 0.1, bright: 0.7 + r() * 0.3 });
              at += Math.round(sr * (0.002 + Math.pow(r(), 2) * 0.05));
            }
          }
        }
      }
      var a = events(ctx, nodes, 31.7, 101, function (d, r, sr, n) { crackle(d, r, sr, n, 4.2); });
      var b = events(ctx, nodes, 43.3, 211, function (d, r, sr, n) { crackle(d, r, sr, n, 2.3); });
      var cr = chain(filter(ctx, "highpass", 140, 0.5), filter(ctx, "lowpass", 8000, 0.5), gain(ctx, 2.3));
      a.connect(cr); b.connect(cr);
      var sum = gain(ctx, 1);
      flick.connect(sum); roar.connect(sum); cr.connect(sum);
      sum.connect(out);
    },

    waves: function (ctx, nodes, out) {
      // one wave's shape as an oscillator: a slow rise, the break, a long
      // pull back. Its rate wanders (7 to 12 s a wave) and each is a little
      // bigger or smaller than the last. Two of them, one each side.
      var H = 24, re = new Float32Array(H + 1), im = new Float32Array(H + 1), N = 512, k, j;
      function shape(x) {
        if (x < 0.5) { return 0.5 - 0.5 * Math.cos(Math.PI * x / 0.5); }      // rise
        if (x < 0.6) { return 1 - 0.35 * (x - 0.5) / 0.1; }                      // the break
        return 0.65 * Math.pow(1 - (x - 0.6) / 0.4, 1.7);                        // pull back
      }
      for (k = 1; k <= H; k++) {
        var a = 0, b = 0;
        for (j = 0; j < N; j++) { var x = j / N, v = shape(x) - 0.42; a += v * Math.cos(2 * Math.PI * k * x); b += v * Math.sin(2 * Math.PI * k * x); }
        re[k] = 2 * a / N; im[k] = 2 * b / N;
      }
      var wave = ctx.createPeriodicWave(re, im, { disableNormalization: true });
      function side(pan, hz, wander, seedOff) {
        var o = ctx.createOscillator(); o.setPeriodicWave(wave); o.frequency.value = hz;
        lfo(ctx, nodes, 0.019 + seedOff, hz * 0.22).connect(o.frequency);
        nodes.push(o);
        var size = gain(ctx, 0.8);                   // this wave bigger, the next smaller
        lfo(ctx, nodes, 0.029 + seedOff * 1.7, 0.2).connect(size.gain);
        o.connect(size);
        // water: noise whose brightness and level follow the wave
        var lp = filter(ctx, "lowpass", 900, 0.7), lvl = gain(ctx, 0.24);
        var toHz = gain(ctx, 1500), toLvl = gain(ctx, 0.56);
        size.connect(toHz); toHz.connect(lp.frequency);
        size.connect(toLvl); toLvl.connect(lvl.gain);
        var body = chain(brown(ctx, nodes, wide(ctx, nodes)), lp, lvl);
        // foam on the break: bright noise, a moment after the peak, only at the top
        var dly = ctx.createDelay(3); dly.delayTime.value = wander;
        var peak = ctx.createWaveShaper(), curve = new Float32Array(257);
        for (j = 0; j < 257; j++) { var y = j / 128 - 1; curve[j] = Math.max(0, y - 0.15) * 1.2; }
        peak.curve = curve;
        var foam = chain(wide(ctx, nodes), filter(ctx, "highpass", 2400, 0.5), filter(ctx, "lowpass", 9000, 0.4), gain(ctx, 0));
        size.connect(dly); dly.connect(peak);
        var toFoam = gain(ctx, 0.2); peak.connect(toFoam); toFoam.connect(foam.gain);
        var p = ctx.createStereoPanner(); p.pan.value = pan;
        body.connect(p); foam.connect(p);
        return p;
      }
      var sum = gain(ctx, 1);
      side(-0.55, 0.098, 0.7, 0).connect(sum);
      side(0.55, 0.083, 0.9, 0.006).connect(sum);
      // the sea out beyond: a low steady rumble in the middle
      chain(brown(ctx, nodes), filter(ctx, "lowpass", 220, 0.5), gain(ctx, 0.18)).connect(sum);
      sum.connect(out);
    }
  };

  // one sound into ctx: its nodes, its own gain (trimmed) to out
  function build(ctx, kind, out) {
    var nodes = [], g = ctx.createGain();
    g.gain.value = TRIM[kind] || 1;
    BUILD[kind](ctx, nodes, g);
    g.connect(out);
    var t = ctx.currentTime;
    nodes.forEach(function (n) { if (n.start) { n.__at != null ? n.start(t, n.__at) : n.start(t); } });
    return { nodes: nodes, out: g };
  }

  // recordings: {kind: url} from the glue (files()); each already at the
  // others' loudness when it was cut, so its trim is 1 unless it says otherwise
  var FILES = {}, FILE_TRIM = { rain: 1, fire: 1, waves: 1 }, held = {};
  function recorded(kind) {
    if (held.kind === kind && held.url === FILES[kind]) { return held.p; }
    var url = FILES[kind];
    var p = fetch(url).then(function (r) {
      if (!r.ok) { throw new Error("no " + kind); }
      return r.arrayBuffer();
    }).then(function (a) {
      return new Promise(function (ok, no) { ac.decodeAudioData(a, ok, no); });
    });
    held = { kind: kind, url: url, p: p };  // one at a time: the last one's samples go
    p.catch(function () { if (held.p === p) { held = {}; } });
    return p;
  }
  function loop(ctx, buf, kind, out) {
    var s = ctx.createBufferSource(), g = ctx.createGain();
    s.buffer = buf; s.loop = true;
    g.gain.value = FILE_TRIM[kind] || 1;
    s.connect(g); g.connect(out);
    s.start(ctx.currentTime, Math.random() * buf.duration);  // somewhere in the loop: never the same opening
    return { nodes: [s, g] };
  }

  var ac = null, master = null, limiter = null, now = null, vol = 0.6;
  function context() {
    if (ac) { return ac; }
    var AC = window.AudioContext || window.webkitAudioContext;
    ac = new AC();
    limiter = ac.createDynamicsCompressor();  // a safety net only: it hardly ever acts
    limiter.threshold.value = -3; limiter.knee.value = 0; limiter.ratio.value = 20;
    limiter.attack.value = 0.003; limiter.release.value = 0.25;
    master = ac.createGain(); master.gain.value = vol;
    master.connect(limiter); limiter.connect(ac.destination);
    return ac;
  }
  function fadeTo(param, v, secs) {
    var t = ac.currentTime;
    param.cancelScheduledValues(t);
    param.setValueAtTime(param.value, t);
    param.linearRampToValueAtTime(v, t + secs);
  }
  function retire(s) {
    if (!s) { return; }
    fadeTo(s.fade.gain, 0, FADE);
    setTimeout(function () {
      s.nodes.forEach(function (n) { try { if (n.stop) { n.stop(); } n.disconnect(); } catch (e) {} });
      try { s.fade.disconnect(); } catch (e) {}
      rest();
    }, FADE * 1000 + 200);
  }
  // nothing playing: the context closes, and what it held goes with it (a
  // minute of a recording is ~23 MB as samples, the noise 4 MB), so a quiet
  // top bar costs nothing (3.9.1: suspended, it kept them all)
  function rest() {
    if (now || !ac) { return; }
    var c = ac;
    ac = master = limiter = null;
    held = {};
    try { c.close(); } catch (e) {}
  }

  window.dcSounds = {
    kinds: KINDS,
    labels: LABELS,
    // Anki's webviews, like browsers, keep sound off till a click on the page;
    // the top bar's may play without one (rooms._allow_sound), so a pick
    // comes back by itself after the bar redraws
    play: function (kind, volume) {
      if (!BUILD[kind]) { return; }
      context();
      if (volume != null) { this.setVolume(volume); }
      if (ac.state === "suspended" && vol > 0) { ac.resume(); }  // 3.9.1: at no volume it stays asleep (the session's check plays every 5 s)
      if (now && now.kind === kind) { return; }
      retire(now);
      var fade = ac.createGain(); fade.gain.value = 0; fade.connect(master);
      var mine = now = { kind: kind, nodes: [], fade: fade };
      function go(buf) {
        if (now !== mine) { return; }  // switched or stopped while it loaded
        mine.nodes = (buf ? loop(ac, buf, kind, fade) : build(ac, kind, fade)).nodes;
        fadeTo(fade.gain, 1, FADE);
      }
      if (FILES[kind]) { recorded(kind).then(go, function () { go(null); }); } else { go(null); }
    },
    // where the recordings are: {rain: url, ...}; a kind left out is made
    files: function (map) {
      var f = {};
      Object.keys(map || {}).forEach(function (k) { if (BUILD[k] && k !== "brown" && typeof map[k] === "string") { f[k] = map[k]; } });
      FILES = f;
    },
    recorded: function () { return Object.keys(FILES); },
    stop: function () { retire(now); now = null; },
    setVolume: function (v) {
      vol = Math.max(0, Math.min(1, +v || 0));
      if (master) { fadeTo(master.gain, vol, 0.08); }
      // 3.9.1: at no volume it sleeps (a running context costs, silent or not); turned up, it wakes
      if (ac && vol > 0 && ac.state === "suspended" && now) { ac.resume(); }
      if (ac && vol === 0) {
        setTimeout(function () { if (vol === 0 && ac && ac.state === "running") { try { ac.suspend(); } catch (e) {} } }, 150);
      }
    },
    playing: function () { return now ? now.kind : null; },
    build: build,
    trim: TRIM
  };
})();
