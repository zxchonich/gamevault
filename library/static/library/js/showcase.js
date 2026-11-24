// Редагування вітрини досягнень у профілі (components/showcase.html).
// Стиль значків — звичайні radio в тій самій формі. Слоти: перетягування мишею/пальцем (pointer events) і стрілками з клавіатури; пул: клік додає/прибирає значок.
(function () {
    const form = document.querySelector("[data-showcase-form]");
    if (!form) return;

    const toggle = document.querySelector("[data-showcase-toggle]");
    const view = document.querySelector("[data-showcase-view]");
    const slots = form.querySelector("[data-showcase-slots]");
    const pool = form.querySelectorAll("[data-showcase-pick]");
    const grip = form.querySelector("[data-showcase-grip]");
    const max = Number(form.dataset.max || 5);
    const initial = slots.innerHTML;

    function keys() {
        return Array.from(slots.children).map((li) => li.dataset.key);
    }

    function syncPool() {
        const chosen = keys();
        pool.forEach((button) => {
            const on = chosen.includes(button.dataset.showcasePick);
            button.setAttribute("aria-pressed", on ? "true" : "false");
            button.disabled = !on && chosen.length >= max;
        });
    }

    function open(state) {
        form.hidden = !state;
        view.hidden = state;
        toggle.setAttribute("aria-expanded", state ? "true" : "false");
        if (!state) {
            slots.innerHTML = initial;
            form.reset(); // повертає й вибраний стиль значків
        }
        syncPool();
    }

    toggle.addEventListener("click", () => open(form.hidden));
    form.querySelector("[data-showcase-cancel]").addEventListener("click", () => open(false));

    pool.forEach((button) => {
        button.addEventListener("click", () => {
            const key = button.dataset.showcasePick;
            const existing = slots.querySelector(`li[data-key="${key}"]`);
            if (existing) {
                existing.remove();
            } else if (keys().length < max) {
                const li = document.createElement("li");
                li.dataset.key = key;
                li.tabIndex = 0;
                li.setAttribute("aria-label", `${button.dataset.title} — стрілками вліво/вправо змінити порядок`);
                li.append(grip.content.cloneNode(true), button.querySelector(".gv-badge").cloneNode(true));
                const title = document.createElement("span");
                title.textContent = button.dataset.title;
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = "keys";
                input.value = key;
                li.append(title, input);
                slots.append(li);
            }
            syncPool();
        });
    });

    // Перетягування: працює і мишею, і на сенсорних екранах.
    let dragging = null;
    slots.addEventListener("pointerdown", (event) => {
        const li = event.target.closest("li");
        if (!li || event.button > 0) return;
        dragging = li;
        li.classList.add("is-dragging");
        li.setPointerCapture(event.pointerId);
    });
    slots.addEventListener("pointermove", (event) => {
        if (!dragging) return;
        const target = document.elementFromPoint(event.clientX, event.clientY);
        const over = target && target.closest("li");
        if (!over || over === dragging || over.parentNode !== slots) return;
        const box = over.getBoundingClientRect();
        const after = event.clientX > box.left + box.width / 2;
        slots.insertBefore(dragging, after ? over.nextSibling : over);
    });
    const stop = () => {
        if (dragging) dragging.classList.remove("is-dragging");
        dragging = null;
    };
    slots.addEventListener("pointerup", stop);
    slots.addEventListener("pointercancel", stop);

    // Клавіатура: стрілки переставляють значок, Delete — прибирає.
    slots.addEventListener("keydown", (event) => {
        const li = event.target.closest("li");
        if (!li) return;
        if (event.key === "ArrowLeft" && li.previousElementSibling) {
            slots.insertBefore(li, li.previousElementSibling);
        } else if (event.key === "ArrowRight" && li.nextElementSibling) {
            slots.insertBefore(li.nextElementSibling, li);
        } else if (event.key === "Delete" || event.key === "Backspace") {
            li.remove();
            syncPool();
            return;
        } else {
            return;
        }
        event.preventDefault();
        li.focus();
    });
})();
