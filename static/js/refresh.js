/**
 * BRIEF Refresh Button
 *
 * Triggers pipeline run via webhook, polls status, reloads on completion.
 */

(function() {
    'use strict';

    const WEBHOOK_URL = 'https://refresh.bezman.ca';
    const TOKEN = '6sefFgFwuRuSZvjoPsnyts-yilTypp-7h9mkhwpE1e8';
    const POLL_INTERVAL = 5000;

    const btn = document.getElementById('refreshBtn');
    const statusEl = document.getElementById('refreshStatus');
    if (!btn) return;

    let polling = false;

    btn.addEventListener('click', async function(e) {
        e.preventDefault();
        if (polling) return;

        btn.classList.add('disabled');
        btn.classList.add('refreshing');
        setStatus('Triggering pipeline...');

        try {
            const resp = await fetch(WEBHOOK_URL + '/trigger', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + TOKEN },
            });

            if (resp.status === 429) {
                const data = await resp.json();
                setStatus(data.detail || 'Rate limited');
                btn.classList.remove('disabled');
                btn.classList.remove('refreshing');
                return;
            }

            if (!resp.ok) {
                setStatus('Error: ' + resp.status);
                btn.classList.remove('disabled');
                btn.classList.remove('refreshing');
                return;
            }

            setStatus('Pipeline running...');
            polling = true;
            pollStatus();

        } catch (err) {
            setStatus('Connection failed');
            btn.classList.remove('disabled');
            btn.classList.remove('refreshing');
        }
    });

    function pollStatus() {
        if (!polling) return;

        fetch(WEBHOOK_URL + '/status')
            .then(r => r.json())
            .then(data => {
                if (data.running) {
                    setStatus('Pipeline running...');
                    setTimeout(pollStatus, POLL_INTERVAL);
                } else {
                    polling = false;
                    if (data.last_error) {
                        setStatus('Error - check logs');
                        btn.classList.remove('disabled');
                        btn.classList.remove('refreshing');
                    } else {
                        setStatus('Done! Reloading...');
                        setTimeout(() => location.reload(), 3000);
                    }
                }
            })
            .catch(() => {
                setTimeout(pollStatus, POLL_INTERVAL);
            });
    }

    function setStatus(msg) {
        if (statusEl) statusEl.textContent = msg;
    }

    // Check if webhook is reachable on load
    fetch(WEBHOOK_URL + '/status')
        .then(r => r.json())
        .then(data => {
            if (data.running) {
                btn.classList.add('disabled');
                btn.classList.add('refreshing');
                setStatus('Pipeline running...');
                polling = true;
                pollStatus();
            }
        })
        .catch(() => {
            btn.title = 'Webhook offline';
        });
})();
