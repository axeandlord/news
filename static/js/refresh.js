/**
 * BRIEF Refresh Button with real pipeline progress.
 *
 * Polls /status for step + progress, drives a thin progress bar under the header.
 */

(function() {
    'use strict';

    const WEBHOOK_URL = 'https://refresh.bezman.ca';
    const TOKEN = '6sefFgFwuRuSZvjoPsnyts-yilTypp-7h9mkhwpE1e8';
    const POLL_INTERVAL = 3000;

    const btn = document.getElementById('refreshBtn');
    const statusEl = document.getElementById('refreshStatus');
    const progressBar = document.getElementById('pipelineProgress');
    const progressFill = document.getElementById('pipelineProgressFill');
    if (!btn) return;

    let polling = false;

    function setStatus(msg) {
        if (statusEl) statusEl.textContent = msg;
    }

    function setProgress(percent) {
        if (!progressBar || !progressFill) return;
        if (percent > 0) {
            progressBar.classList.add('active');
            progressFill.style.width = percent + '%';
        } else {
            progressFill.style.width = '0%';
            progressBar.classList.remove('active');
        }
    }

    function startUI() {
        btn.classList.add('disabled', 'refreshing');
        setProgress(2);
    }

    function resetBtn() {
        btn.classList.remove('disabled', 'refreshing');
        setProgress(0);
    }

    btn.addEventListener('click', async function(e) {
        e.preventDefault();
        if (polling || btn.classList.contains('disabled')) return;

        startUI();
        setStatus('Triggering...');

        try {
            const resp = await fetch(WEBHOOK_URL + '/trigger', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + TOKEN },
            });

            if (resp.status === 429) {
                const data = await resp.json();
                resetBtn();
                setStatus(data.detail || 'Rate limited');
                return;
            }

            if (!resp.ok) {
                resetBtn();
                setStatus('Error: ' + resp.status);
                return;
            }

            polling = true;
            pollStatus();

        } catch (err) {
            resetBtn();
            setStatus('Connection failed');
        }
    });

    function pollStatus() {
        if (!polling) return;

        fetch(WEBHOOK_URL + '/status')
            .then(r => r.json())
            .then(data => {
                if (data.running) {
                    setProgress(Math.max(data.progress || 2, 2));
                    setStatus(data.step || 'Working...');
                    setTimeout(pollStatus, POLL_INTERVAL);
                } else {
                    polling = false;
                    if (data.last_error) {
                        resetBtn();
                        setStatus('Error - check logs');
                    } else {
                        setProgress(100);
                        setStatus('Done! Reloading...');
                        setTimeout(() => location.reload(), 2000);
                    }
                }
            })
            .catch(() => {
                setTimeout(pollStatus, POLL_INTERVAL);
            });
    }

    // On page load: check if a run is already in progress
    fetch(WEBHOOK_URL + '/status')
        .then(r => r.json())
        .then(data => {
            if (data.running) {
                startUI();
                setStatus(data.step || 'Pipeline running...');
                setProgress(Math.max(data.progress || 2, 2));
                polling = true;
                pollStatus();
            }
        })
        .catch(() => {
            btn.title = 'Webhook offline';
        });
})();
