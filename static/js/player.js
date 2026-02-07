/**
 * BRIEF Segment-Based Audio Player with waveform visualization.
 *
 * Plays per-segment MP3s as a playlist. Prev/Next skip between topic segments.
 * Falls back to single-file mode if no segment data is available.
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
        this.segmentLabel = document.getElementById('segmentLabel');
        this.segmentTicks = document.getElementById('segmentTicks');
        this.speedBtn = document.querySelector('.speed-btn');
        this.skipBack = document.querySelector('.skip-back');
        this.skipForward = document.querySelector('.skip-forward');
        this.heroSection = document.querySelector('.hero');
        this.completionBanner = document.getElementById('completionBanner');

        this.stickyPlayer = document.querySelector('.sticky-player');
        this.stickyPlayBtn = document.querySelector('.sticky-play-btn');
        this.stickyTime = document.querySelector('.sticky-time');
        this.stickyProgressFill = document.querySelector('.sticky-progress-fill');
        this.stickyProgress = document.querySelector('.sticky-progress');
        this.stickySpeed = document.querySelector('.sticky-speed');
        this.stickyWaveform = document.querySelector('.sticky-waveform');
        this.stickySegmentLabel = document.querySelector('.sticky-segment-label');

        this.speeds = [1, 1.25, 1.5, 1.75, 2];
        this.currentSpeedIndex = 0;
        this.isPlaying = false;

        // Segment playlist
        this.segments = [];
        this.currentSegment = 0;
        this.totalDuration = 0;
        this.hasSegments = false;

        // Heard tracking
        this.heardHashes = new Set();
        this.HEARD_KEY = 'brief_heard';
        this.WEBHOOK_URL = 'https://refresh.bezman.ca';

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
        this.smoothed = [];

        this.init();
    }

    init() {
        this.loadSegments(window.BRIEF_SEGMENTS_EN);
        this.pruneHeardStorage();
        this.createWaveform();
        this.bindEvents();
        this.updateTimeDisplay();
        this.updateSegmentLabel();
        this.renderSegmentTicks();
        this.drawIdleWaveform();
    }

    // === Segment Management ===

    loadSegments(data) {
        this.segments = [];
        this.currentSegment = 0;
        this.totalDuration = 0;
        this.hasSegments = false;

        if (data && data.segments && data.segments.length > 1) {
            this.segments = data.segments;
            this.totalDuration = this.segments.reduce(function(sum, s) { return sum + s.duration; }, 0);
            this.hasSegments = true;
        }

        this.updateSegmentLabel();
        this.renderSegmentTicks();
    }

    getSegmentStartTime(index) {
        var t = 0;
        for (var i = 0; i < index && i < this.segments.length; i++) {
            t += this.segments[i].duration;
        }
        return t;
    }

    getTotalElapsed() {
        if (!this.hasSegments) return this.audio.currentTime;
        return this.getSegmentStartTime(this.currentSegment) + (this.audio.currentTime || 0);
    }

    getTotalDuration() {
        if (!this.hasSegments) return this.audio.duration || 0;
        return this.totalDuration;
    }

    // === Segment Navigation ===

    loadSegment(index, autoPlay) {
        if (!this.hasSegments || index < 0 || index >= this.segments.length) return;

        this.currentSegment = index;
        var seg = this.segments[index];

        this.audio.src = seg.file;
        this.audio.load();
        this.audio.playbackRate = this.speeds[this.currentSpeedIndex];

        this.updateSegmentLabel();

        if (autoPlay) {
            var self = this;
            this.audio.addEventListener('canplay', function onCanPlay() {
                self.audio.removeEventListener('canplay', onCanPlay);
                self.audio.play();
            });
        }
    }

    nextSegment() {
        if (!this.hasSegments) {
            // Fallback: skip forward 30s
            this.audio.currentTime = Math.min(this.audio.duration, this.audio.currentTime + 30);
            return;
        }

        // Mark current segment as heard
        this.markSegmentHeard(this.currentSegment);

        if (this.currentSegment < this.segments.length - 1) {
            this.loadSegment(this.currentSegment + 1, this.isPlaying);
        }
    }

    prevSegment() {
        if (!this.hasSegments) {
            // Fallback: skip back 30s
            this.audio.currentTime = Math.max(0, this.audio.currentTime - 30);
            return;
        }

        // If more than 3s into segment, restart current; else go to previous
        if (this.audio.currentTime > 3 && this.currentSegment >= 0) {
            this.audio.currentTime = 0;
        } else if (this.currentSegment > 0) {
            this.loadSegment(this.currentSegment - 1, this.isPlaying);
        } else {
            this.audio.currentTime = 0;
        }
    }

    // === Heard Tracking ===

    markSegmentHeard(index) {
        if (!this.hasSegments || index >= this.segments.length) return;

        var seg = this.segments[index];
        if (!seg.article_hashes || seg.article_hashes.length === 0) return;

        var newHashes = [];
        for (var i = 0; i < seg.article_hashes.length; i++) {
            var h = seg.article_hashes[i];
            if (!this.heardHashes.has(h)) {
                this.heardHashes.add(h);
                newHashes.push(h);
            }
        }

        if (newHashes.length === 0) return;

        // Store in localStorage
        this.saveHeardStorage();

        // Fire-and-forget POST to /heard
        try {
            fetch(this.WEBHOOK_URL + '/heard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ heard_hashes: newHashes }),
            }).catch(function() {});
        } catch (e) {}
    }

    saveHeardStorage() {
        try {
            var data = {
                hashes: Array.from(this.heardHashes),
                timestamp: new Date().toISOString(),
            };
            localStorage.setItem(this.HEARD_KEY, JSON.stringify(data));
        } catch (e) {}
    }

    pruneHeardStorage() {
        try {
            var raw = localStorage.getItem(this.HEARD_KEY);
            if (!raw) return;
            var data = JSON.parse(raw);
            var age = Date.now() - new Date(data.timestamp).getTime();
            if (age > 24 * 60 * 60 * 1000) {
                localStorage.removeItem(this.HEARD_KEY);
            } else if (data.hashes) {
                for (var i = 0; i < data.hashes.length; i++) {
                    this.heardHashes.add(data.hashes[i]);
                }
            }
        } catch (e) {
            localStorage.removeItem(this.HEARD_KEY);
        }
    }

    // === UI Updates ===

    updateSegmentLabel() {
        if (!this.segmentLabel) return;

        if (!this.hasSegments || this.segments.length === 0) {
            this.segmentLabel.textContent = '';
            if (this.stickySegmentLabel) this.stickySegmentLabel.textContent = '';
            return;
        }

        var seg = this.segments[this.currentSegment];
        var label = seg.section + ' (' + (this.currentSegment + 1) + '/' + this.segments.length + ')';
        this.segmentLabel.textContent = label;
        if (this.stickySegmentLabel) this.stickySegmentLabel.textContent = label;
    }

    renderSegmentTicks() {
        if (!this.segmentTicks || !this.hasSegments || this.totalDuration <= 0) {
            if (this.segmentTicks) this.segmentTicks.innerHTML = '';
            return;
        }

        this.segmentTicks.innerHTML = '';
        // Skip first segment boundary (it's at 0%)
        for (var i = 1; i < this.segments.length; i++) {
            var pos = (this.getSegmentStartTime(i) / this.totalDuration) * 100;
            var tick = document.createElement('div');
            tick.className = 'segment-tick';
            tick.style.left = pos + '%';
            this.segmentTicks.appendChild(tick);
        }
    }

    // === Waveform ===

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
            var timeSample = Math.abs(this.timeData[binIdx] - 128) / 128;
            var freqBin = Math.floor((i / this.heroBars.length) * binCount * 0.6);
            var freqSample = this.freqData[freqBin] / 255;
            var value = timeSample * 0.5 + freqSample * 0.5;

            this.smoothed[i] += (value - this.smoothed[i]) * 0.3;
            var v = this.smoothed[i];

            this.heroBars[i].style.height = (v * 60 + 4) + 'px';
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
        var t = (this.getTotalElapsed()) * 8;

        for (var i = 0; i < this.heroBars.length; i++) {
            var pos = i / this.heroBars.length;
            var wave1 = Math.sin(t + i * 0.4) * 0.3;
            var wave2 = Math.sin(t * 1.7 + i * 0.7) * 0.2;
            var wave3 = Math.sin(t * 0.5 + i * 0.15) * 0.25;
            var burst = Math.max(0, Math.sin(t * 0.3 + i * 0.05)) * 0.25;
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

    // === Event Binding ===

    bindEvents() {
        this.playBtn.addEventListener('click', () => this.togglePlay());
        this.stickyPlayBtn.addEventListener('click', () => this.togglePlay());
        this.progressBar.addEventListener('click', e => this.seek(e));
        this.stickyProgress.addEventListener('click', e => this.seekSticky(e));
        this.speedBtn.addEventListener('click', () => this.cycleSpeed());
        this.stickySpeed.addEventListener('click', () => this.cycleSpeed());
        this.skipBack.addEventListener('click', () => this.prevSegment());
        this.skipForward.addEventListener('click', () => this.nextSegment());
        window.addEventListener('scroll', () => this.handleScroll());

        this.audio.addEventListener('timeupdate', () => this.onTimeUpdate());
        this.audio.addEventListener('loadedmetadata', () => this.updateTimeDisplay());
        this.audio.addEventListener('ended', () => this.onSegmentEnded());
        this.audio.addEventListener('play', () => this.onPlay());
        this.audio.addEventListener('pause', () => this.onPause());
    }

    togglePlay() {
        this.initAudioContext();
        if (this.audioCtx && this.audioCtx.state === 'suspended') {
            this.audioCtx.resume();
        }

        // If no segments loaded yet and we have segment data, start from segment 0
        if (this.hasSegments && !this.audio.src.includes('segment-')) {
            this.loadSegment(0, true);
            return;
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

        // Hide completion banner if showing
        if (this.completionBanner) this.completionBanner.style.display = 'none';
    }

    onPause() {
        this.isPlaying = false;
        this.playBtn.classList.remove('playing');
        setTimeout(() => { if (!this.isPlaying) this.drawIdleWaveform(); }, 300);
    }

    onSegmentEnded() {
        // Mark current segment as heard
        this.markSegmentHeard(this.currentSegment);

        if (this.hasSegments && this.currentSegment < this.segments.length - 1) {
            // Auto-advance to next segment
            this.loadSegment(this.currentSegment + 1, true);
        } else {
            // Briefing complete
            this.isPlaying = false;
            this.playBtn.classList.remove('playing');
            this.drawIdleWaveform();
            this.onBriefingComplete();
        }
    }

    onBriefingComplete() {
        // Show completion banner
        if (this.completionBanner) {
            this.completionBanner.style.display = '';
        }

        // Auto-trigger refresh after short delay
        setTimeout(function() {
            var refreshBtn = document.getElementById('refreshBtn');
            if (refreshBtn) refreshBtn.click();
        }, 3000);
    }

    onTimeUpdate() {
        var totalElapsed = this.getTotalElapsed();
        var totalDur = this.getTotalDuration();

        if (totalDur > 0) {
            var progress = (totalElapsed / totalDur) * 100;
            this.progressFill.style.width = progress + '%';
            this.progressHandle.style.left = progress + '%';
            this.stickyProgressFill.style.width = progress + '%';
        }

        this.updateTimeDisplay();

        // Mark segment heard when > 80% listened
        if (this.hasSegments && this.audio.duration > 0) {
            var segProgress = this.audio.currentTime / this.audio.duration;
            if (segProgress > 0.8) {
                this.markSegmentHeard(this.currentSegment);
            }
        }
    }

    updateTimeDisplay() {
        var elapsed = this.getTotalElapsed();
        var total = this.getTotalDuration();
        var c = this.formatTime(elapsed);
        var d = this.formatTime(total);
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
        var pct = (e.clientX - r.left) / r.width;

        if (this.hasSegments && this.totalDuration > 0) {
            var targetTime = pct * this.totalDuration;
            // Find which segment this maps to
            var elapsed = 0;
            for (var i = 0; i < this.segments.length; i++) {
                if (elapsed + this.segments[i].duration > targetTime) {
                    var seekWithin = targetTime - elapsed;
                    if (i !== this.currentSegment) {
                        this.loadSegment(i, this.isPlaying);
                        // Seek after load
                        var self = this;
                        var target = seekWithin;
                        this.audio.addEventListener('loadedmetadata', function onMeta() {
                            self.audio.removeEventListener('loadedmetadata', onMeta);
                            self.audio.currentTime = target;
                        });
                    } else {
                        this.audio.currentTime = seekWithin;
                    }
                    return;
                }
                elapsed += this.segments[i].duration;
            }
        } else {
            this.audio.currentTime = pct * (this.audio.duration || 0);
        }
    }

    seekSticky(e) {
        var r = this.stickyProgress.getBoundingClientRect();
        var pct = (e.clientX - r.left) / r.width;

        if (this.hasSegments && this.totalDuration > 0) {
            // Reuse seek logic by creating a mock event
            var mockRect = this.progressBar.getBoundingClientRect();
            var mockEvent = { clientX: mockRect.left + pct * mockRect.width };
            this.seek(mockEvent);
        } else {
            this.audio.currentTime = pct * (this.audio.duration || 0);
        }
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

document.addEventListener('DOMContentLoaded', () => window.briefPlayer = new BriefPlayer());
