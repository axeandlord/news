/**
 * BRIEF Audio Player with real-time waveform visualization.
 *
 * Uses Web Audio API AnalyserNode for actual frequency data.
 */
class BriefPlayer {
    constructor() {
        this.audio = document.getElementById('briefAudio');
        if (!this.audio) return;

        // Hero elements
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

        // Sticky elements
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

        // Web Audio API
        this.audioCtx = null;
        this.analyser = null;
        this.dataArray = null;
        this.audioSource = null;

        // Bar references
        this.heroBars = [];
        this.stickyBars = [];

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

        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 256;
        this.analyser.smoothingTimeConstant = 0.8;

        this.audioSource = this.audioCtx.createMediaElementSource(this.audio);
        this.audioSource.connect(this.analyser);
        this.analyser.connect(this.audioCtx.destination);

        this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    }

    createWaveform() {
        var heroCount = 80;
        var stickyCount = 50;

        for (var i = 0; i < heroCount; i++) {
            var bar = document.createElement('div');
            bar.className = 'waveform-bar';
            this.waveformContainer.appendChild(bar);
            this.heroBars.push(bar);
        }

        for (var i = 0; i < stickyCount; i++) {
            var bar = document.createElement('div');
            bar.className = 'waveform-bar';
            bar.style.width = '2px';
            this.stickyWaveform.appendChild(bar);
            this.stickyBars.push(bar);
        }
    }

    drawIdleWaveform() {
        // Static waveform that looks like a real audio file preview
        for (var i = 0; i < this.heroBars.length; i++) {
            var t = i / this.heroBars.length;
            // Envelope: louder in middle, quieter at edges
            var envelope = Math.sin(t * Math.PI) * 0.7 + 0.3;
            // Pseudo-random but deterministic per bar position
            var seed = Math.sin(i * 127.1 + 311.7) * 43758.5453;
            var noise = seed - Math.floor(seed);
            var h = (noise * 35 + 10) * envelope;
            this.heroBars[i].style.height = h + 'px';
            this.heroBars[i].style.opacity = '0.35';
        }

        for (var i = 0; i < this.stickyBars.length; i++) {
            var seed = Math.sin(i * 127.1 + 311.7) * 43758.5453;
            var noise = seed - Math.floor(seed);
            this.stickyBars[i].style.height = (noise * 15 + 5) + 'px';
            this.stickyBars[i].style.opacity = '0.35';
        }
    }

    drawLiveWaveform() {
        if (!this.isPlaying || !this.analyser) return;

        this.analyser.getByteFrequencyData(this.dataArray);

        var binCount = this.dataArray.length; // 128

        // Hero bars: map frequency bins to bar heights
        for (var i = 0; i < this.heroBars.length; i++) {
            // Map bar index to frequency bin (focus on lower frequencies for voice)
            var binIndex = Math.floor((i / this.heroBars.length) * binCount * 0.7);
            var value = this.dataArray[binIndex] || 0;
            // Scale 0-255 to reasonable pixel height
            var h = (value / 255) * 60 + 4;
            this.heroBars[i].style.height = h + 'px';
            this.heroBars[i].style.opacity = Math.min(0.4 + (value / 255) * 0.6, 1);
        }

        // Sticky bars
        for (var i = 0; i < this.stickyBars.length; i++) {
            var binIndex = Math.floor((i / this.stickyBars.length) * binCount * 0.7);
            var value = this.dataArray[binIndex] || 0;
            var h = (value / 255) * 24 + 3;
            this.stickyBars[i].style.height = h + 'px';
            this.stickyBars[i].style.opacity = Math.min(0.4 + (value / 255) * 0.6, 1);
        }

        requestAnimationFrame(() => this.drawLiveWaveform());
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
        if (this.audioCtx.state === 'suspended') {
            this.audioCtx.resume();
        }
        this.audio.paused ? this.audio.play() : this.audio.pause();
    }

    onPlay() {
        this.isPlaying = true;
        this.playBtn.classList.add('playing');
        this.playbackControls.classList.add('visible');
        this.progressContainer.classList.add('visible');
        this.drawLiveWaveform();
    }

    onPause() {
        this.isPlaying = false;
        this.playBtn.classList.remove('playing');
        // Fade back to idle waveform
        setTimeout(() => {
            if (!this.isPlaying) this.drawIdleWaveform();
        }, 300);
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
