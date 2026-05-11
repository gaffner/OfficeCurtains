/*
 * Shared page chrome bootstrap.
 *
 * Every page in the app needs the same dark-mode initialization
 * (read preference from localStorage, apply .dark-mode to <body>).
 * The home page (index.html) additionally renders the actual toggle
 * switch and a hamburger menu. This file handles both cases.
 *
 * Include with `<script src="js/chrome.js" defer></script>` in <head>.
 */
(function () {
    // ---- Dark-mode init (runs on every page) ----
    if (localStorage.getItem('dark-mode') === 'true') {
        // Apply immediately to avoid a flash of light theme. Body may not
        // exist yet when the script runs deferred from <head>; in that
        // case we re-check on DOMContentLoaded below.
        if (document.body) {
            document.body.classList.add('dark-mode');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const isDark = localStorage.getItem('dark-mode') === 'true';
        if (isDark) {
            document.body.classList.add('dark-mode');
        }

        // ---- Toggle switch (only present on pages that render it, e.g. index.html) ----
        const toggle = document.getElementById('dark-mode-toggle');
        if (toggle) {
            toggle.checked = isDark;
            toggle.addEventListener('change', function () {
                document.body.classList.toggle('dark-mode');
                localStorage.setItem('dark-mode', String(toggle.checked));
            });
        }

        // ---- Hamburger menu (also index-only today) ----
        const menuButton = document.querySelector('.menu-button');
        const sidebar = document.querySelector('.sidebar');
        const overlay = document.querySelector('.overlay');
        if (menuButton && sidebar) {
            const toggleMenu = function () {
                menuButton.classList.toggle('active');
                sidebar.classList.toggle('active');
                if (overlay) overlay.classList.toggle('active');
            };
            menuButton.addEventListener('click', toggleMenu);
            if (overlay) overlay.addEventListener('click', toggleMenu);
        }
    });
})();
