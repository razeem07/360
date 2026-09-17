// Signal preview chart: candles from marketdata's API (same shape/logic as
// Stock Analysis) + entry/exit markers from strategies' preview API.
(function () {
    const scriptTag = document.currentScript;
    const candleUrl = scriptTag.dataset.candleApi;
    const previewUrl = scriptTag.dataset.previewApi;
    const container = document.getElementById("preview-chart");
    if (!container || !candleUrl || !previewUrl) return;

    const chart = LightweightCharts.createChart(container, {
        layout: { background: { color: "transparent" }, textColor: "#8b949e" },
        grid: { vertLines: { color: "#30363d" }, horzLines: { color: "#30363d" } },
        timeScale: { borderColor: "#30363d" },
        rightPriceScale: { borderColor: "#30363d" },
    });
    const candleSeries = chart.addCandlestickSeries({
        upColor: "#3fb950", downColor: "#f85149", borderVisible: false,
        wickUpColor: "#3fb950", wickDownColor: "#f85149",
    });

    function resize() {
        chart.resize(container.clientWidth, container.clientHeight);
    }
    window.addEventListener("resize", resize);

    Promise.all([
        fetch(candleUrl, { credentials: "same-origin" }).then((r) => r.json()),
        fetch(previewUrl, { credentials: "same-origin" }).then((r) => r.json()),
    ])
        .then(([candleData, previewData]) => {
            candleSeries.setData(candleData.bars);

            const entryMarkers = (previewData.entry_times || []).map((time) => ({
                time, position: "belowBar", color: "#3fb950", shape: "arrowUp", text: "Entry",
            }));
            const exitMarkers = (previewData.exit_times || []).map((time) => ({
                time, position: "aboveBar", color: "#f85149", shape: "arrowDown", text: "Exit",
            }));
            const markers = entryMarkers.concat(exitMarkers).sort((a, b) => {
                const ta = typeof a.time === "number" ? a.time : Date.parse(a.time);
                const tb = typeof b.time === "number" ? b.time : Date.parse(b.time);
                return ta - tb;
            });
            candleSeries.setMarkers(markers);

            chart.timeScale().fitContent();
            resize();
        })
        .catch((err) => {
            container.innerHTML = '<div class="placeholder">Could not load preview.</div>';
            console.error("Failed to load signal preview:", err);
        });
})();
