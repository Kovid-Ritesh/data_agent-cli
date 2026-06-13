/* ==========================================================================
   DataAgent CLI — Client-Side Script (Interactions & Terminal Simulator)
   ========================================================================== */

// ── Tab Switching ─────────────────────────────────────────────────────────
function switchTab(event, tabId) {
    // Hide all tab panels
    const panels = document.querySelectorAll('.tab-panel');
    panels.forEach(panel => panel.classList.remove('active'));

    // Deactivate all tab buttons
    const buttons = document.querySelectorAll('.tab-btn');
    buttons.forEach(btn => btn.classList.remove('active'));

    // Show selected tab panel and activate button
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
}

// ── Copy to Clipboard ──────────────────────────────────────────────────────
function copyText(elementId, btnElement) {
    const codeElement = document.getElementById(elementId);
    if (!codeElement) return;

    const textToCopy = codeElement.innerText || codeElement.textContent;

    navigator.clipboard.writeText(textToCopy).then(() => {
        // Change icon to checkmark
        const icon = btnElement.querySelector('i');
        icon.className = 'fa-solid fa-check';
        btnElement.classList.add('copied');

        // Reset icon after 2 seconds
        setTimeout(() => {
            icon.className = 'fa-regular fa-copy';
            btnElement.classList.remove('copied');
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
    });
}

// ── Interactive Terminal Replay Simulation ─────────────────────────────────
const terminalContent = document.getElementById('terminal-content');

const SIMULATION_STEPS = [
    { type: 'input', text: 'dagent "summarize sales.csv and plot a bar chart of sales by region"' },
    { type: 'log', text: '✓ Discovered data files in workspace.\n  → Auto-loading sales.csv (8 rows × 4 columns)...' },
    { type: 'think', title: 'Thinking', text: 'We need to:\n1. Load the sales.csv dataset (already preloaded in `dfs[\'sales\']`).\n2. Group the data by `region` and calculate the sum of `sales` or `revenue`.\n3. Verify column names of `dfs[\'sales\']` first.\n4. Call `quick_bar()` to save a bar chart and output the result.' },
    { type: 'code', title: 'Executing Code', text: "import pandas as pd\nprint(dfs['sales'].columns.tolist())\nprint(dfs['sales'].head(3))" },
    { type: 'result', text: "[EXECUTION RESULT]\n['region', 'rep', 'sales', 'revenue']\n\n  region      rep  sales  revenue\n0   East    Sarah   1500    45000\n1   West  Michael   2100    63000\n2   East     John    950    28500" },
    { type: 'think', title: 'Thinking', text: 'Columns are: `region`, `rep`, `sales`, `revenue`.\nNow we will:\n1. Group by `region` and sum the `revenue`.\n2. Call `quick_bar(df, \'region\', \'revenue\', \'Revenue by Region\')` to save the chart.' },
    { type: 'code', title: 'Executing Code', text: "summary = dfs['sales'].groupby('region')['revenue'].sum().reset_index()\nfrom tabulate import tabulate\nprint(tabulate(summary, headers='keys', tablefmt='rounded_outline'))\n\nchart_path = quick_bar(dfs['sales'], 'region', 'revenue', title='Revenue by Region')\nprint(f'Chart saved to {chart_path}')" },
    { type: 'result', text: `[EXECUTION RESULT]
╭───┬──────────┬───────────╮
│   │ region   │   revenue │
├───┼──────────┼───────────┤
│ 0 │ East     │     73500 │
│ 1 │ West     │    126000 │
│ 2 │ North    │     58000 │
╰───┴──────────┴───────────╯
Chart saved to ./output/bar_region_revenue.png` },
    { type: 'answer', title: 'Answer', text: `### Sales Summary by Region

Here is the summary of the total revenue across the different regions:
- **West**: $126,000 (Highest sales volume)
- **East**: $73,500
- **North**: $58,000

The bar chart representing this comparison has been plotted and saved to:
📂 **\`./output/bar_region_revenue.png\`**` }
];

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function typeWriter(text, element, speed = 25) {
    for (let i = 0; i < text.length; i++) {
        element.textContent += text.charAt(i);
        await sleep(speed);
    }
}

async function runTerminalSimulation() {
    if (!terminalContent) return;

    while (true) {
        terminalContent.innerHTML = '';
        
        for (const step of SIMULATION_STEPS) {
            await sleep(800);

            if (step.type === 'input') {
                const line = document.createElement('div');
                line.className = 'term-line';
                
                const prompt = document.createElement('span');
                prompt.className = 'term-prompt';
                prompt.textContent = '[DataAgent] > ';
                line.appendChild(prompt);

                const cmd = document.createElement('span');
                cmd.className = 'term-cmd';
                line.appendChild(cmd);
                
                terminalContent.appendChild(line);
                terminalContent.scrollTop = terminalContent.scrollHeight;

                await typeWriter(step.text, cmd, 30);
            } 
            else if (step.type === 'log') {
                const line = document.createElement('div');
                line.className = 'term-line';
                line.style.color = '#9ca3af';
                line.style.whiteSpace = 'pre-line';
                line.textContent = step.text;
                terminalContent.appendChild(line);
            }
            else if (step.type === 'think') {
                const panel = document.createElement('div');
                panel.className = 'term-panel-think';
                
                const title = document.createElement('div');
                title.style.color = '#ffbd2e';
                title.style.fontWeight = 'bold';
                title.style.marginBottom = '6px';
                title.textContent = `🤔 ${step.title}`;
                panel.appendChild(title);

                const body = document.createElement('div');
                body.style.whiteSpace = 'pre-line';
                body.style.color = '#d1d5db';
                body.style.fontSize = '0.85rem';
                body.textContent = step.text;
                panel.appendChild(body);

                terminalContent.appendChild(panel);
            }
            else if (step.type === 'code') {
                const panel = document.createElement('div');
                panel.className = 'term-panel-exec';
                
                const title = document.createElement('div');
                title.style.color = '#06b6d4';
                title.style.fontWeight = 'bold';
                title.style.marginBottom = '6px';
                title.textContent = `⚙️ ${step.title}`;
                panel.appendChild(title);

                const body = document.createElement('pre');
                body.style.margin = '0';
                body.style.color = '#a5f3fc';
                body.style.fontSize = '0.85rem';
                body.textContent = step.text;
                panel.appendChild(body);

                terminalContent.appendChild(panel);
            }
            else if (step.type === 'result') {
                const panel = document.createElement('pre');
                panel.className = 'term-dataframe';
                panel.textContent = step.text;
                terminalContent.appendChild(panel);
            }
            else if (step.type === 'answer') {
                const panel = document.createElement('div');
                panel.className = 'term-panel-ans';
                
                const title = document.createElement('div');
                title.style.color = '#10b981';
                title.style.fontWeight = 'bold';
                title.style.marginBottom = '6px';
                title.textContent = `🎯 ${step.title}`;
                panel.appendChild(title);

                const body = document.createElement('div');
                body.style.whiteSpace = 'pre-line';
                body.style.color = '#a7f3d0';
                body.style.fontSize = '0.85rem';
                body.textContent = step.text;
                panel.appendChild(body);

                terminalContent.appendChild(panel);
            }

            terminalContent.scrollTop = terminalContent.scrollHeight;
        }

        // Wait before restarting loop
        await sleep(8000);
    }
}

// ── Initialize ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    runTerminalSimulation();
});
