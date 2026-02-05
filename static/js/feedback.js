/**
 * BRIEF v2 Feedback System
 *
 * Tracks user engagement (clicks, likes, dislikes) for learning.
 * Stores feedback locally and syncs to server API.
 */

(function() {
    'use strict';

    const STORAGE_KEY = 'brief_feedback';
    const API_ENDPOINT = '/api/feedback';

    // Initialize feedback storage
    function getStoredFeedback() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {
                clicks: {},
                feedback: {},
                pendingSync: []
            };
        } catch {
            return { clicks: {}, feedback: {}, pendingSync: [] };
        }
    }

    function saveFeedback(data) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            console.warn('Could not save feedback:', e);
        }
    }

    // Track article clicks
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

        // Add to pending sync
        data.pendingSync.push({
            type: 'click',
            hash: hash,
            category: category,
            timestamp: now
        });

        saveFeedback(data);

        // Try to sync
        syncToServer(data);
    }

    // Track explicit feedback (like/dislike)
    function trackFeedback(hash, category, action) {
        const data = getStoredFeedback();
        const now = new Date().toISOString();

        // Store feedback
        data.feedback[hash] = {
            action: action,
            category: category,
            timestamp: now
        };

        // Add to pending sync
        data.pendingSync.push({
            type: 'feedback',
            hash: hash,
            category: category,
            action: action,
            timestamp: now
        });

        saveFeedback(data);

        // Try to sync
        syncToServer(data);
    }

    // Sync pending feedback to server
    async function syncToServer(data) {
        if (data.pendingSync.length === 0) return;

        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    events: data.pendingSync
                })
            });

            if (response.ok) {
                // Clear pending sync on success
                data.pendingSync = [];
                saveFeedback(data);
            }
        } catch (e) {
            // Server not available, keep pending for later
            console.log('Feedback sync deferred');
        }
    }

    // Update UI for feedback button state
    function updateButtonState(button, isActive) {
        if (isActive) {
            button.classList.add('active');
        } else {
            button.classList.remove('active');
        }
    }

    // Initialize click tracking on article links
    function initClickTracking() {
        document.querySelectorAll('.article-link, .article-link-title').forEach(link => {
            link.addEventListener('click', function(e) {
                const hash = this.dataset.hash;
                const article = this.closest('.article');
                const category = article ? article.dataset.category : '';

                if (hash) {
                    trackClick(hash, category);
                }
            });
        });
    }

    // Initialize feedback buttons
    function initFeedbackButtons() {
        const data = getStoredFeedback();

        document.querySelectorAll('.feedback-btn').forEach(button => {
            const hash = button.dataset.hash;
            const action = button.dataset.action;

            // Restore saved state
            if (data.feedback[hash]) {
                const savedAction = data.feedback[hash].action;
                if (savedAction === action) {
                    button.classList.add('active');
                }
            }

            // Handle click
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const hash = this.dataset.hash;
                const category = this.dataset.category;
                const action = this.dataset.action;

                // Toggle state
                const isActive = this.classList.contains('active');

                // Clear other button in pair
                const parent = this.parentElement;
                parent.querySelectorAll('.feedback-btn').forEach(btn => {
                    btn.classList.remove('active');
                });

                if (!isActive) {
                    this.classList.add('active');
                    trackFeedback(hash, category, action);

                    // Visual feedback
                    this.style.transform = 'scale(1.2)';
                    setTimeout(() => {
                        this.style.transform = '';
                    }, 150);
                }
            });
        });
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        initClickTracking();
        initFeedbackButtons();

        // Try to sync any pending feedback on load
        const data = getStoredFeedback();
        if (data.pendingSync.length > 0) {
            syncToServer(data);
        }
    }
})();
