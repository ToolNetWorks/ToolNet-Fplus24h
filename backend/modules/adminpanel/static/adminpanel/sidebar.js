(() => {
    "use strict";

    const toggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("adminSidebar");
    const backdrop = document.getElementById("sidebarBackdrop");

    if (!toggle || !sidebar || !backdrop) return;

    const media = window.matchMedia("(max-width: 960px)");
    const storageKey = "toolnet_sidebar_collapsed";

    let collapsed = false;
    let mobileOpen = false;

    try {
        collapsed = localStorage.getItem(storageKey) === "1";
    } catch (_) {
        collapsed = false;
    }

    function render() {
        const mobile = media.matches;

        document.body.classList.toggle(
            "sidebar-collapsed",
            !mobile && collapsed
        );

        document.body.classList.toggle(
            "sidebar-open",
            mobile && mobileOpen
        );

        backdrop.hidden = !(mobile && mobileOpen);

        const expanded = mobile ? mobileOpen : !collapsed;

        toggle.setAttribute(
            "aria-expanded",
            String(expanded)
        );

        toggle.setAttribute(
            "aria-label",
            expanded ? "Thu gọn menu" : "Mở menu"
        );
    }

    function closeMobileMenu() {
        if (!mobileOpen) return;

        mobileOpen = false;
        render();
    }

    toggle.addEventListener("click", () => {
        if (media.matches) {
            mobileOpen = !mobileOpen;
            render();
            return;
        }

        collapsed = !collapsed;

        try {
            localStorage.setItem(
                storageKey,
                collapsed ? "1" : "0"
            );
        } catch (_) {
            // Storage unavailable: keep in-memory state.
        }

        render();
    });

    backdrop.addEventListener("click", closeMobileMenu);

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        closeMobileMenu();
    });

    sidebar.addEventListener("click", (event) => {
        if (!media.matches) return;
        if (!event.target.closest("a[href]")) return;

        closeMobileMenu();
    });

    window.addEventListener("resize", () => {
        if (!media.matches) mobileOpen = false;
        render();
    });

    render();
})();
