/**
 * Time-aware greeting for BRIEF.
 */
(function() {
    'use strict';

    var h = new Date().getHours();
    var greeting, sub;

    if (h < 5) {
        greeting = 'Burning the midnight oil, sir.';
        sub = 'Here\'s what happened while the world slept.';
    } else if (h < 12) {
        greeting = 'Good morning, sir.';
        sub = 'Your briefing is ready.';
    } else if (h < 17) {
        greeting = 'Good afternoon, sir.';
        sub = 'Here\'s what you may have missed.';
    } else if (h < 21) {
        greeting = 'Good evening, sir.';
        sub = 'Your evening briefing awaits.';
    } else {
        greeting = 'Good evening, sir.';
        sub = 'A late-night debrief for you.';
    }

    var el = document.getElementById('greeting');
    var sub_el = document.getElementById('greetingSub');
    if (el) el.textContent = greeting;
    if (sub_el) sub_el.textContent = sub;
})();
