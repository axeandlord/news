/**
 * BRIEF v2 Feedback System
 *
 * Tracks user engagement (clicks, likes, dislikes) in localStorage.
 * Export button lets user download feedback JSON for pipeline import.
 */

(function() {
    'use strict';

    const STORAGE_KEY = 'brief_feedback';
    const WEBHOOK_URL = 'https://refresh.bezman.ca';

    function sendToWebhook(hash, category, action) {
        try {
            fetch(WEBHOOK_URL + '/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hash, category, action })
            }).catch(() => {}); // fire-and-forget
        } catch { /* ignore */ }
    }

    function getStoredFeedback() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {
                clicks: {},
                feedback: {}
            };
        } catch {
            return { clicks: {}, feedback: {} };
        }
    }

    function saveFeedback(data) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            console.warn('Could not save feedback:', e);
        }
    }

    function trackClick(hash, category) {
        const data = getStoredFeedback();
        const now = new Date().toISOString();

        if (!data.clicks[hash]) {
            data.clicks[hash] = {
                category: category,
                firstClick: now,
                clickCount: 0
            };
        }

        data.clicks[hash].clickCount++;
        data.clicks[hash].lastClick = now;

        saveFeedback(data);
        sendToWebhook(hash, category, 'click');
    }

    function trackFeedback(hash, category, action) {
        const data = getStoredFeedback();
        const now = new Date().toISOString();

        data.feedback[hash] = {
            action: action,
            category: category,
            timestamp: now
        };

        saveFeedback(data);
        sendToWebhook(hash, category, action);
    }

    function exportFeedback() {
        const data = getStoredFeedback();
        const hasData = Object.keys(data.clicks).length > 0 || Object.keys(data.feedback).length > 0;
        if (!hasData) return;

        const exportData = {
            exported_at: new Date().toISOString(),
            clicks: data.clicks,
            feedback: data.feedback
        };

        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'brief-feedback-' + new Date().toISOString().slice(0, 10) + '.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function initClickTracking() {
        document.querySelectorAll('.article-link, .article-link-title').forEach(link => {
            link.addEventListener('click', function() {
                const hash = this.dataset.hash;
                const article = this.closest('.article');
                const category = article ? article.dataset.category : '';

                if (hash) {
                    trackClick(hash, category);
                }
            });
        });
    }

    function initFeedbackButtons() {
        const data = getStoredFeedback();

        document.querySelectorAll('.feedback-btn').forEach(button => {
            const hash = button.dataset.hash;
            const action = button.dataset.action;

            // Restore saved state
            if (data.feedback[hash] && data.feedback[hash].action === action) {
                button.classList.add('active');
            }

            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const hash = this.dataset.hash;
                const category = this.dataset.category;
                const action = this.dataset.action;
                const isActive = this.classList.contains('active');

                // Clear other button in pair
                const parent = this.parentElement;
                parent.querySelectorAll('.feedback-btn').forEach(btn => {
                    btn.classList.remove('active');
                });

                if (!isActive) {
                    this.classList.add('active');
                    trackFeedback(hash, category, action);

                    this.style.transform = 'scale(1.2)';
                    setTimeout(() => {
                        this.style.transform = '';
                    }, 150);
                }
            });
        });
    }

    function initExportButton() {
        const data = getStoredFeedback();
        const hasData = Object.keys(data.clicks).length > 0 || Object.keys(data.feedback).length > 0;

        const exportLink = document.getElementById('exportFeedback');
        if (exportLink) {
            if (hasData) {
                exportLink.style.display = 'inline';
                exportLink.addEventListener('click', function(e) {
                    e.preventDefault();
                    exportFeedback();
                });
            } else {
                exportLink.style.display = 'none';
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        initClickTracking();
        initFeedbackButtons();
        initExportButton();
    }
})();
