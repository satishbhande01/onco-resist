<script>
    // Conversation history — accumulated across turns
    // so the LLM remembers what was said earlier in the session
    let chatHistory = [];

    // Optional: page context injected by detail pages
    // e.g. "Viewing drug: Imatinib (BCR-ABL Inhibitor)"
    // Child templates can override this variable
    const pageContext = "{% block page_context %}{% endblock %}";

    function toggleChat() {
        const panel = document.getElementById('chatPanel');
        panel.classList.toggle('open');
        if (panel.classList.contains('open')) {
            document.getElementById('chatInput').focus();
        }
    }

    function appendMessage(role, text) {
        const container = document.getElementById('chatMessages');
        const div = document.createElement('div');
        div.className = `chat-msg ${role}`;
        div.textContent = text;
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

            // Strip the LLM's References block —
            // the UI renders source_details separately
            let answer = data.answer || "Sorry, no response.";
            if (answer.includes('## References')) {
                answer = answer.split('## References')[0].trim();
            }

            thinking.remove();
            appendMessage('assistant', answer);

            // Update history for the next turn
            chatHistory = data.history || [];

        } catch (e) {
            thinking.remove();
            appendMessage('assistant', 'Something went wrong. Please try again.');
        }
    }
</script>

