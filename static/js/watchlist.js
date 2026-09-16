// Watchlist search/add/remove — plain fetch() + full-page navigation on
// success (no SPA state sync), consistent with the rest of this app.
(function () {
    const scriptTag = document.currentScript;
    const toggleUrl = scriptTag.dataset.toggleUrl;
    const currentSymbol = scriptTag.dataset.currentSymbol || "";
    const currentTimeframe = scriptTag.dataset.currentTimeframe || "1d";

    const allInstrumentsEl = document.getElementById("all-instruments-data");
    const watchlistIdsEl = document.getElementById("watchlist-ids-data");
    if (!allInstrumentsEl || !watchlistIdsEl) return;

    const allInstruments = JSON.parse(allInstrumentsEl.textContent);
    const watchlistIds = new Set(JSON.parse(watchlistIdsEl.textContent));

    function getCookie(name) {
        const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
        return match ? decodeURIComponent(match[2]) : null;
    }

    function toggleWatchlist(internalId, onSuccess) {
        fetch(toggleUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: "internal_id=" + encodeURIComponent(internalId),
        })
            .then((res) => res.json())
            .then(onSuccess)
            .catch((err) => console.error("Watchlist toggle failed:", err));
    }

    function goToSymbol(internalId) {
        const params = new URLSearchParams({ symbol: internalId, timeframe: currentTimeframe });
        window.location.href = "?" + params.toString();
    }

    // --- Search box -------------------------------------------------
    const searchInput = document.getElementById("instrument-search");
    const resultsEl = document.getElementById("search-results");

    function renderResults(query) {
        resultsEl.innerHTML = "";
        if (!query) return;
        const q = query.trim().toLowerCase();
        const matches = allInstruments
            .filter((i) => i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q))
            .slice(0, 8);

        if (matches.length === 0) {
            resultsEl.innerHTML = '<div class="sidebar-empty">No matches.</div>';
            return;
        }

        matches.forEach((inst) => {
            const row = document.createElement("div");
            row.className = "instrument-row";
            const inWatchlist = watchlistIds.has(inst.internal_id);
            row.innerHTML =
                '<a href="#" data-internal-id="' + inst.internal_id + '">' + inst.symbol + "</a>" +
                '<button type="button" data-internal-id="' + inst.internal_id + '">' + (inWatchlist ? "★" : "+") + "</button>";

            row.querySelector("a").addEventListener("click", (e) => {
                e.preventDefault();
                goToSymbol(inst.internal_id);
            });
            row.querySelector("button").addEventListener("click", () => {
                toggleWatchlist(inst.internal_id, () => goToSymbol(inst.internal_id));
            });
            resultsEl.appendChild(row);
        });
    }

    if (searchInput) {
        searchInput.addEventListener("input", (e) => renderResults(e.target.value));
    }

    // --- Watchlist sidebar remove buttons ----------------------------
    document.querySelectorAll(".watchlist-remove").forEach((btn) => {
        btn.addEventListener("click", () => {
            toggleWatchlist(btn.dataset.internalId, () => window.location.reload());
        });
    });

    // --- "Add/In Watchlist" button on the selected stock's card -----
    const currentToggleBtn = document.getElementById("watchlist-toggle-current");
    if (currentToggleBtn) {
        currentToggleBtn.addEventListener("click", () => {
            toggleWatchlist(currentToggleBtn.dataset.internalId, () => window.location.reload());
        });
    }
})();
