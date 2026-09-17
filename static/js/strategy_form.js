// Dynamic entry/exit condition builder. No framework — plain DOM, matches
// the rest of this app's vanilla-JS stack. Serializes to the rule schema
// strategies/rules.py evaluates: {"all"|"any": [{left, operator, right}]}.
(function () {
    const INDICATORS = [
        { value: "close", label: "Close", needsPeriod: false },
        { value: "open", label: "Open", needsPeriod: false },
        { value: "high", label: "High", needsPeriod: false },
        { value: "low", label: "Low", needsPeriod: false },
        { value: "volume", label: "Volume", needsPeriod: false },
        { value: "sma", label: "SMA", needsPeriod: true, defaultPeriod: 20 },
        { value: "ema", label: "EMA", needsPeriod: true, defaultPeriod: 20 },
        { value: "rsi", label: "RSI", needsPeriod: true, defaultPeriod: 14 },
        { value: "atr", label: "ATR", needsPeriod: true, defaultPeriod: 14 },
        { value: "vwap", label: "Rolling VWAP", needsPeriod: true, defaultPeriod: 20 },
        { value: "macd_line", label: "MACD Line", needsPeriod: false },
        { value: "macd_signal", label: "MACD Signal", needsPeriod: false },
        { value: "macd_hist", label: "MACD Histogram", needsPeriod: false },
    ];
    const OPERATORS = [
        ["<", "<"], ["<=", "<="], [">", ">"], [">=", ">="], ["==", "=="],
        ["crosses_above", "crosses above"], ["crosses_below", "crosses below"],
    ];

    function operandFieldsHTML(side) {
        const indicatorOptions = INDICATORS.map((i) => `<option value="${i.value}">${i.label}</option>`).join("");
        return `
            <select class="${side}-type" style="width:auto;">
                <option value="indicator">Indicator</option>
                <option value="value">Fixed value</option>
            </select>
            <select class="${side}-indicator" style="width:auto;">${indicatorOptions}</select>
            <input type="number" class="${side}-period" placeholder="period" style="width:5rem;">
            <input type="number" step="0.01" class="${side}-value" placeholder="value" style="width:6rem; display:none;">
        `;
    }

    function buildConditionRow() {
        const row = document.createElement("div");
        row.className = "instrument-row";
        row.style.flexWrap = "wrap";
        row.style.gap = "0.4rem";
        row.innerHTML = `
            ${operandFieldsHTML("left")}
            <select class="operator" style="width:auto;">
                ${OPERATORS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
            </select>
            ${operandFieldsHTML("right")}
            <button type="button" class="remove-row" style="width:auto;">&times;</button>
        `;

        row.querySelectorAll(".left-type, .right-type").forEach((sel) => {
            sel.addEventListener("change", () => updateOperandVisibility(row, sel.classList[0].split("-")[0]));
        });
        row.querySelectorAll(".left-indicator, .right-indicator").forEach((sel) => {
            sel.addEventListener("change", () => updateIndicatorVisibility(row, sel.classList[0].split("-")[0]));
        });
        row.querySelector(".remove-row").addEventListener("click", () => row.remove());

        updateOperandVisibility(row, "left");
        updateOperandVisibility(row, "right");
        return row;
    }

    function updateOperandVisibility(row, side) {
        const type = row.querySelector(`.${side}-type`).value;
        row.querySelector(`.${side}-indicator`).style.display = type === "indicator" ? "" : "none";
        row.querySelector(`.${side}-value`).style.display = type === "value" ? "" : "none";
        if (type === "indicator") updateIndicatorVisibility(row, side);
        else row.querySelector(`.${side}-period`).style.display = "none";
    }

    function updateIndicatorVisibility(row, side) {
        const indicatorName = row.querySelector(`.${side}-indicator`).value;
        const meta = INDICATORS.find((i) => i.value === indicatorName);
        const periodInput = row.querySelector(`.${side}-period`);
        periodInput.style.display = meta && meta.needsPeriod ? "" : "none";
        if (meta && meta.needsPeriod && !periodInput.value) periodInput.value = meta.defaultPeriod;
    }

    function populateRow(row, condition) {
        ["left", "right"].forEach((side) => {
            const operand = condition[side] || {};
            if ("value" in operand) {
                row.querySelector(`.${side}-type`).value = "value";
                row.querySelector(`.${side}-value`).value = operand.value;
            } else if (operand.indicator) {
                row.querySelector(`.${side}-type`).value = "indicator";
                row.querySelector(`.${side}-indicator`).value = operand.indicator;
                if (operand.params && operand.params.period !== undefined) {
                    row.querySelector(`.${side}-period`).value = operand.params.period;
                }
            }
            updateOperandVisibility(row, side);
        });
        row.querySelector(".operator").value = condition.operator || "<";
    }

    function readOperand(row, side) {
        const type = row.querySelector(`.${side}-type`).value;
        if (type === "value") {
            return { value: parseFloat(row.querySelector(`.${side}-value`).value) };
        }
        const indicatorName = row.querySelector(`.${side}-indicator`).value;
        const meta = INDICATORS.find((i) => i.value === indicatorName);
        const operand = { indicator: indicatorName };
        if (meta && meta.needsPeriod) {
            operand.params = { period: parseInt(row.querySelector(`.${side}-period`).value, 10) || meta.defaultPeriod };
        }
        return operand;
    }

    function serializeSection(containerId, combinatorId) {
        const rows = document.querySelectorAll(`#${containerId} .instrument-row`);
        const conditions = Array.from(rows).map((row) => ({
            left: readOperand(row, "left"),
            operator: row.querySelector(".operator").value,
            right: readOperand(row, "right"),
        }));
        const combinator = document.getElementById(combinatorId).value;
        return { [combinator]: conditions };
    }

    function loadInitial(containerId, dataElementId) {
        const el = document.getElementById(dataElementId);
        if (!el) return;
        const data = JSON.parse(el.textContent);
        if (!data) return;
        const conditions = data.all || data.any || [];
        const container = document.getElementById(containerId);
        conditions.forEach((condition) => {
            const row = buildConditionRow();
            container.appendChild(row);
            populateRow(row, condition);
        });
        const combinatorSelect = document.getElementById(containerId === "entry-conditions" ? "entry-combinator" : "exit-combinator");
        if (data.any) combinatorSelect.value = "any";
    }

    document.querySelectorAll(".rule-add-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.getElementById(`${btn.dataset.target}-conditions`).appendChild(buildConditionRow());
        });
    });

    loadInitial("entry-conditions", "initial-entry-rules");
    loadInitial("exit-conditions", "initial-exit-rules");

    document.getElementById("strategy-form").addEventListener("submit", () => {
        document.getElementById("entry_rules_json").value = JSON.stringify(serializeSection("entry-conditions", "entry-combinator"));
        document.getElementById("exit_rules_json").value = JSON.stringify(serializeSection("exit-conditions", "exit-combinator"));
    });
})();
