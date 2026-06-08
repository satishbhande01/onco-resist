// Conversation history
let chatHistory = [];

// Page context — overridden by detail pages via extra_scripts
let pageContext = "";

function toggleChat() {
    const panel = document.getElementById('chatPanel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) {
        document.getElementById('chatInput').focus();
    }
}

function appendMessage(role, text) {
    const container = document.getElementById('chatMessages');
    const div       = document.createElement('div');
    div.className   = `chat-msg ${role}`;

    if (role === 'assistant') {
        div.innerHTML = marked.parse(text);
        div.querySelectorAll('a').forEach(link => {
            const href = link.getAttribute('href');
            if (href && href.startsWith('/')) {
                link.target = '_self';
            } else {
                link.target = '_blank';
                link.rel    = 'noopener noreferrer';
            }
        });
    } else {
        div.textContent = text;
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

async function sendChat() {
    const input   = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    appendMessage('user', message);

    const thinking = appendMessage('thinking', '● thinking…');

    try {
        const res = await fetch('/api/chat', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: chatHistory,
                context: pageContext,
            }),
        });

        const data = await res.json();

        let answer = data.answer || "Sorry, no response.";
        if (answer.includes('## References')) {
            answer = answer.split('## References')[0].trim();
        }

        thinking.remove();
        appendMessage('assistant', answer);
        chatHistory = data.history || [];

    } catch (e) {
        thinking.remove();
        appendMessage('assistant', 'Something went wrong. Please try again.');
    }
}