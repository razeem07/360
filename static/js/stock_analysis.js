// Static historical chart only (PRD §8's explicit build order: static chart
// first, live layer later). Vanilla JS + lightweight-charts, no framework.
(function () {
    const scriptTag = document.currentScript;
    const apiUrl = scriptTag.dataset.candleApi;
    const container = document.getElementById("chart");
    if (!container || !apiUrl) return;

    const chart = LightweightCharts.createChart(container, {
        layout: {
            background: { color: "transparent" },
            textColor: "#8b949e",
        },
        grid: {
            vertLines: { color: "#30363d" },
            horzLines: { color: "#30363d" },
        },
        timeScale: { borderColor: "#30363d" },
        rightPriceScale: { borderColor: "#30363d" },
    });

    const candleSeries = chart.addCandlestickSeries({
        upColor: "#3fb950",
        downColor: "#f85149",
        borderVisible: false,
        wickUpColor: "#3fb950",
        wickDownColor: "#f85149",
    });
    const sma20Series = chart.addLineSeries({ color: "#58a6ff", lineWidth: 1 });
    const ema50Series = chart.addLineSeries({ color: "#d29922", lineWidth: 1 });

    function resize() {
        chart.resize(container.clientWidth, container.clientHeight);
    }
    window.addEventListener("resize", resize);

    fetch(apiUrl, { credentials: "same-origin" })
        .then((res) => res.json())
        .then((data) => {
            candleSeries.setData(data.bars);
            sma20Series.setData(data.sma20);
            ema50Series.setData(data.ema50);
            chart.timeScale().fitContent();
            resize();
        })
        .catch((err) => {
            container.innerHTML = '<div class="placeholder">Could not load chart data.</div>';
            console.error("Failed to load candle data:", err);
        });
})();
