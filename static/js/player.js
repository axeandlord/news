/**
 * BRIEF Audio Player with real-time waveform visualization.
 *
 * Uses Web Audio API AnalyserNode for actual audio data.
 * Falls back to amplitude simulation if CORS blocks analyser.
 */
class BriefPlayer {
    constructor() {
        this.audio = document.getElementById('briefAudio');
        if (!this.audio) return;

        this.playBtn = document.getElementById('playBtn');
        this.waveformContainer = document.querySelector('.waveform-container');
        this.playbackControls = document.querySelector('.playback-controls');
        this.progressContainer = document.querySelector('.progress-container');
        this.progressFill = document.querySelector('.progress-fill');
        this.progressHandle = document.querySelector('.progress-handle');
        this.progressBar = document.querySelector('.progress-bar');
        this.timeDisplay = document.querySelector('.time-display');
        this.speedBtn = document.querySelector('.speed-btn');
        this.skipBack = document.querySelector('.skip-back');
        this.skipForward = document.querySelector('.skip-forward');
        this.heroSection = document.querySelector('.hero');

        this.stickyPlayer = document.querySelector('.sticky-player');
        this.stickyPlayBtn = document.querySelector('.sticky-play-btn');
        this.stickyTime = document.querySelector('.sticky-time');
        this.stickyProgressFill = document.querySelector('.sticky-progress-fill');
        this.stickyProgress = document.querySelector('.sticky-progress');
        this.stickySpeed = document.querySelector('.sticky-speed');
        this.stickyWaveform = document.querySelector('.sticky-waveform');

        this.speeds = [1, 1.25, 1.5, 1.75, 2];
        this.currentSpeedIndex = 0;
        this.isPlaying = false;

        // Web Audio
        this.audioCtx = null;
        this.analyser = null;
        this.timeData = null;
        this.freqData = null;
        this.audioSource = null;
        this.analyserWorking = false;
        this.checkedAnalyser = false;

        // Bars
        this.heroBars = [];
        this.stickyBars = [];

        // Smoothed values for fallback animation
        this.smoothed = [];

        this.init();
    }

    init() {
        this.createWaveform();
        this.bindEvents();
        this.updateTimeDisplay();
        this.drawIdleWaveform();
    }

    initAudioContext() {
        if (this.audioCtx) return;
        try {
            this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            this.analyser = this.audioCtx.createAnalyser();
            this.analyser.fftSize = 256;
            this.analyser.smoothingTimeConstant = 0.75;

            this.audioSource = this.audioCtx.createMediaElementSource(this.audio);
            this.audioSource.connect(this.analyser);
            this.analyser.connect(this.audioCtx.destination);

            var bufLen = this.analyser.frequencyBinCount;
            this.timeData = new Uint8Array(bufLen);
            this.freqData = new Uint8Array(bufLen);
        } catch (e) {
            this.audioCtx = null;
        }
    }

    createWaveform() {
        for (var i = 0; i < 80; i++) {
            var bar = document.createElement('div');
            bar.className = 'waveform-bar';
            this.waveformContainer.appendChild(bar);
            this.heroBars.push(bar);
            this.smoothed.push(0);
        }
        for (var i = 0; i < 50; i++) {
            var bar = document.createElement('div');
            bar.className = 'waveform-bar';
            bar.style.width = '2px';
            this.stickyWaveform.appendChild(bar);
            this.stickyBars.push(bar);
        }
    }

    drawIdleWaveform() {
        for (var i = 0; i < this.heroBars.length; i++) {
            var t = i / this.heroBars.length;
            var envelope = Math.sin(t * Math.PI) * 0.7 + 0.3;
            var seed = Math.sin(i * 127.1 + 311.7) * 43758.5453;
            var noise = seed - Math.floor(seed);
            var h = (noise * 35 + 10) * envelope;
            this.heroBars[i].style.height = h + 'px';
            this.heroBars[i].style.opacity = '0.35';
            this.smoothed[i] = 0;
        }
        for (var i = 0; i < this.stickyBars.length; i++) {
            var seed = Math.sin(i * 127.1 + 311.7) * 43758.5453;
            var noise = seed - Math.floor(seed);
            this.stickyBars[i].style.height = (noise * 15 + 5) + 'px';
            this.stickyBars[i].style.opacity = '0.35';
        }
    }

    checkAnalyserData() {
        if (!this.analyser || this.checkedAnalyser) return;
        this.analyser.getByteFrequencyData(this.freqData);
        var sum = 0;
        for (var i = 0; i < this.freqData.length; i++) sum += this.freqData[i];
        this.analyserWorking = sum > 0;
        if (this.analyserWorking) this.checkedAnalyser = true;
    }

    drawLiveWaveform() {
        if (!this.isPlaying) return;

        // Check if analyser returns real data (CORS can block it)
        if (this.analyser && !this.checkedAnalyser) {
            this.checkAnalyserData();
        }

        if (this.analyser && this.analyserWorking) {
            this.drawFromAnalyser();
        } else {
            this.drawFallback();
        }

        requestAnimationFrame(() => this.drawLiveWaveform());
    }

    drawFromAnalyser() {
        this.analyser.getByteTimeDomainData(this.timeData);
        this.analyser.getByteFrequencyData(this.freqData);
        var binCount = this.timeData.length;

        for (var i = 0; i < this.heroBars.length; i++) {
            var binIdx = Math.floor((i / this.heroBars.length) * binCount);

            // Mix time-domain (waveform shape) and frequency (energy)
            var timeSample = Math.abs(this.timeData[binIdx] - 128) / 128;
            var freqBin = Math.floor((i / this.heroBars.length) * binCount * 0.6);
            var freqSample = this.freqData[freqBin] / 255;

            var value = timeSample * 0.5 + freqSample * 0.5;

            // Smooth
            this.smoothed[i] += (value - this.smoothed[i]) * 0.3;
            var v = this.smoothed[i];

            var h = v * 60 + 4;
            this.heroBars[i].style.height = h + 'px';
            this.heroBars[i].style.opacity = (0.4 + v * 0.6).toFixed(2);
        }

        for (var i = 0; i < this.stickyBars.length; i++) {
            var binIdx = Math.floor((i / this.stickyBars.length) * binCount);
            var timeSample = Math.abs(this.timeData[binIdx] - 128) / 128;
            var freqBin = Math.floor((i / this.stickyBars.length) * binCount * 0.6);
            var freqSample = this.freqData[freqBin] / 255;
            var v = timeSample * 0.5 + freqSample * 0.5;
            this.stickyBars[i].style.height = (v * 24 + 3) + 'px';
            this.stickyBars[i].style.opacity = (0.4 + v * 0.6).toFixed(2);
        }
    }

    drawFallback() {
        // Fallback: simulate voice-like waveform from audio currentTime
        // Creates a convincing voice visualization without analyser data
        var t = this.audio.currentTime * 8;

        for (var i = 0; i < this.heroBars.length; i++) {
            var pos = i / this.heroBars.length;

            // Layer multiple sine waves for organic speech-like pattern
            var wave1 = Math.sin(t + i * 0.4) * 0.3;
            var wave2 = Math.sin(t * 1.7 + i * 0.7) * 0.2;
            var wave3 = Math.sin(t * 0.5 + i * 0.15) * 0.25;
            var burst = Math.max(0, Math.sin(t * 0.3 + i * 0.05)) * 0.25;

            // Center emphasis (speech is centered in spectrum)
            var center = 1 - Math.abs(pos - 0.5) * 1.2;
            center = Math.max(center, 0.2);

            var value = (0.3 + wave1 + wave2 + wave3 + burst) * center;
            value = Math.max(0.05, Math.min(1, value));

            this.smoothed[i] += (value - this.smoothed[i]) * 0.15;
            var v = this.smoothed[i];

            this.heroBars[i].style.height = (v * 55 + 6) + 'px';
            this.heroBars[i].style.opacity = (0.4 + v * 0.55).toFixed(2);
        }

        for (var i = 0; i < this.stickyBars.length; i++) {
            var pos = i / this.stickyBars.length;
            var wave = Math.sin(t + i * 0.5) * 0.3 + Math.sin(t * 1.5 + i * 0.8) * 0.2;
            var center = 1 - Math.abs(pos - 0.5) * 1.2;
            var v = (0.3 + wave) * Math.max(center, 0.2);
            this.stickyBars[i].style.height = (v * 22 + 3) + 'px';
            this.stickyBars[i].style.opacity = (0.4 + v * 0.5).toFixed(2);
        }
    }

    bindEvents() {
        this.playBtn.addEventListener('click', () => this.togglePlay());
        this.stickyPlayBtn.addEventListener('click', () => this.togglePlay());
        this.audio.addEventListener('timeupdate', () => this.onTimeUpdate());
        this.audio.addEventListener('loadedmetadata', () => this.updateTimeDisplay());
        this.audio.addEventListener('ended', () => this.onEnded());
        this.audio.addEventListener('play', () => this.onPlay());
        this.audio.addEventListener('pause', () => this.onPause());
        this.progressBar.addEventListener('click', e => this.seek(e));
        this.stickyProgress.addEventListener('click', e => this.seekSticky(e));
        this.speedBtn.addEventListener('click', () => this.cycleSpeed());
        this.stickySpeed.addEventListener('click', () => this.cycleSpeed());
        this.skipBack.addEventListener('click', () => this.skip(-15));
        this.skipForward.addEventListener('click', () => this.skip(15));
        window.addEventListener('scroll', () => this.handleScroll());
    }

    togglePlay() {
        this.initAudioContext();
        if (this.audioCtx && this.audioCtx.state === 'suspended') {
            this.audioCtx.resume();
        }
        this.audio.paused ? this.audio.play() : this.audio.pause();
    }

    onPlay() {
        this.isPlaying = true;
        this.checkedAnalyser = false;
        this.analyserWorking = false;
        this.playBtn.classList.add('playing');
        this.playbackControls.classList.add('visible');
        this.progressContainer.classList.add('visible');
        this.drawLiveWaveform();
    }

    onPause() {
        this.isPlaying = false;
        this.playBtn.classList.remove('playing');
        setTimeout(() => { if (!this.isPlaying) this.drawIdleWaveform(); }, 300);
    }

    onEnded() {
        this.isPlaying = false;
        this.playBtn.classList.remove('playing');
        this.drawIdleWaveform();
    }

    onTimeUpdate() {
        var progress = (this.audio.currentTime / this.audio.duration) * 100;
        this.progressFill.style.width = progress + '%';
        this.progressHandle.style.left = progress + '%';
        this.stickyProgressFill.style.width = progress + '%';
        this.updateTimeDisplay();
    }

    updateTimeDisplay() {
        var c = this.formatTime(this.audio.currentTime);
        var d = this.formatTime(this.audio.duration || 0);
        var t = c + ' / ' + d;
        this.timeDisplay.textContent = t;
        this.stickyTime.textContent = t;
    }

    formatTime(s) {
        if (isNaN(s)) return '0:00';
        var m = Math.floor(s / 60);
        var sec = Math.floor(s % 60);
        return m + ':' + sec.toString().padStart(2, '0');
    }

    seek(e) {
        var r = this.progressBar.getBoundingClientRect();
        this.audio.currentTime = ((e.clientX - r.left) / r.width) * this.audio.duration;
    }

    seekSticky(e) {
        var r = this.stickyProgress.getBoundingClientRect();
        this.audio.currentTime = ((e.clientX - r.left) / r.width) * this.audio.duration;
    }

    skip(s) {
        this.audio.currentTime = Math.max(0, Math.min(this.audio.duration, this.audio.currentTime + s));
    }

    cycleSpeed() {
        this.currentSpeedIndex = (this.currentSpeedIndex + 1) % this.speeds.length;
        var s = this.speeds[this.currentSpeedIndex];
        this.audio.playbackRate = s;
        this.speedBtn.textContent = s + 'x';
        this.stickySpeed.textContent = s + 'x';
    }

    handleScroll() {
        var h = this.heroSection.getBoundingClientRect().bottom;
        if (h < 0 && this.isPlaying) {
            this.stickyPlayer.classList.add('visible');
        } else {
            this.stickyPlayer.classList.remove('visible');
        }
    }
}

document.addEventListener('DOMContentLoaded', () => new BriefPlayer());
