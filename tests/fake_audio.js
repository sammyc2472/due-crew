// tests: a Web Audio context that only says what was asked of it (log), and
// timers that run when flushed, for sounds.js in node (test_room_sounds_v391)
var log = [];
function param() { return { value: 0, setValueAtTime: function () {}, linearRampToValueAtTime: function () {}, cancelScheduledValues: function () {}, setTargetAtTime: function () {}, exponentialRampToValueAtTime: function () {} }; }
function node() {
  return new Proxy({ connect: function () {}, disconnect: function () {}, start: function () {}, stop: function () {} }, {
    get: function (t, k) { if (k in t) { return t[k]; } if (typeof k === 'string') { t[k] = param(); return t[k]; } } });
}
function AC() {
  var me = this; this.state = 'running'; this.currentTime = 0; this.sampleRate = 8000; this.destination = node();
  this.suspend = function () { log.push('suspend'); me.state = 'suspended'; return Promise.resolve(); };
  this.resume = function () { log.push('resume'); me.state = 'running'; return Promise.resolve(); };
  this.close = function () { log.push('close'); me.state = 'closed'; return Promise.resolve(); };
  this.createBuffer = function (c, n) { return { duration: n / 8000, getChannelData: function () { return new Float32Array(n); } }; };
  log.push('new');
}
['createGain', 'createDynamicsCompressor', 'createBufferSource', 'createBiquadFilter', 'createOscillator', 'createIIRFilter',
 'createStereoPanner', 'createChannelMerger', 'createChannelSplitter', 'createWaveShaper', 'createConstantSource', 'createDelay'].forEach(function (k) { AC.prototype[k] = function () { return node(); }; });
var window = { AudioContext: AC };
var timers = [];
var setTimeout = function (f) { timers.push(f); };
function flush() { var t = timers; timers = []; t.forEach(function (f) { f(); }); }
