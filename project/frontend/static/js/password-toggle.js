/**
 * Reusable accessible Password Show/Hide Toggle for Bhagya Laxmi Library
 * Uses document-level event delegation so that all present and dynamically
 * added password toggle buttons work seamlessly across all pages and modals.
 */
(function () {
    function findPasswordInput(button) {
        // 1. Prefer input inside the same relative/parent container
        const container = button.closest(".relative") || button.parentElement;
        if (container) {
            const input = container.querySelector("input");
            if (input) return input;
        }

        // 2. Fallback to data-target ID lookup
        const targetId = button.getAttribute("data-target");
        if (targetId) {
            // First search within the same form if possible
            const form = button.closest("form");
            if (form) {
                const formInput = form.querySelector("#" + CSS.escape(targetId));
                if (formInput) return formInput;
            }
            return document.getElementById(targetId);
        }

        return null;
    }

    function toggleVisibility(button) {
        const input = findPasswordInput(button);
        if (!input) return;

        const eyeOpen = button.querySelector(".eye-open-icon");
        const eyeClosed = button.querySelector(".eye-closed-icon");

        if (input.type === "password") {
            input.type = "text";
            button.setAttribute("aria-label", "Hide password");
            button.setAttribute("aria-pressed", "true");
            if (eyeOpen) eyeOpen.classList.add("hidden");
            if (eyeClosed) eyeClosed.classList.remove("hidden");
        } else {
            input.type = "password";
            button.setAttribute("aria-label", "Show password");
            button.setAttribute("aria-pressed", "false");
            if (eyeOpen) eyeOpen.classList.remove("hidden");
            if (eyeClosed) eyeClosed.classList.add("hidden");
        }
    }

    // Event delegation on document for click events
    document.addEventListener("click", function (e) {
        const button = e.target.closest("[data-password-toggle]");
        if (button) {
            e.preventDefault();
            toggleVisibility(button);
        }
    });

    // Event delegation on document for keyboard events (Enter / Space)
    document.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
            const button = e.target.closest("[data-password-toggle]");
            if (button) {
                e.preventDefault();
                toggleVisibility(button);
            }
        }
    });

    // Ensure buttons have proper accessibility attributes
    function setupAttributes() {
        document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
            if (!button.hasAttribute("type")) {
                button.setAttribute("type", "button");
            }
            if (!button.hasAttribute("aria-label")) {
                button.setAttribute("aria-label", "Show password");
            }
            if (!button.hasAttribute("aria-pressed")) {
                button.setAttribute("aria-pressed", "false");
            }
            if (!button.hasAttribute("tabindex")) {
                button.setAttribute("tabindex", "0");
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupAttributes);
    } else {
        setupAttributes();
    }

    // Also expose globally if manual re-init is ever called
    window.initPasswordToggles = setupAttributes;
})();
