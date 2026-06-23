class ChatApp {
    constructor() {
        this.threadId = this.generateThreadId();
        this.imageUrl = null;
        this.imagePreviewUrl = null;
        this.isUploading = false;
        this.isLoading = false;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadHistory();
    }

    generateThreadId() {
        let id = localStorage.getItem('chat_thread_id');
        if (!id) {
            id = 'thread_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('chat_thread_id', id);
        }
        return id;
    }

    setupEventListeners() {
        const sendBtn = document.getElementById('sendBtn');
        const messageInput = document.getElementById('messageInput');
        const imageInput = document.getElementById('imageInput');
        const clearBtn = document.getElementById('clearBtn');

        sendBtn.addEventListener('click', () => this.sendMessage());
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        imageInput.addEventListener('change', (e) => this.handleImageUpload(e));

        clearBtn.addEventListener('click', () => this.clearChat());
    }

    async handleImageUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        if (!file.type.startsWith('image/')) {
            alert('请选择图片文件');
            return;
        }

        if (file.size > 5 * 1024 * 1024) {
            alert('图片大小不能超过5MB');
            return;
        }

        this.imageUrl = null;
        this.imagePreviewUrl = URL.createObjectURL(file);
        document.getElementById('imagePreview').textContent = '上传中: ' + file.name;

        try {
            this.isUploading = true;
            this.imageUrl = await this.uploadImageToOSS(file);
            document.getElementById('imagePreview').textContent = '已上传: ' + file.name;
        } catch (error) {
            console.error('图片上传错误:', error);
            alert('图片上传失败: ' + error.message);
            this.clearSelectedImage();
        } finally {
            this.isUploading = false;
            event.target.value = '';
        }
    }

    clearSelectedImage() {
        this.imageUrl = null;
        if (this.imagePreviewUrl) {
            URL.revokeObjectURL(this.imagePreviewUrl);
            this.imagePreviewUrl = null;
        }
        document.getElementById('imagePreview').textContent = '';
    }

    async uploadImageToOSS(file) {
        const filename = Date.now() + '_' + file.name.replace(/\s+/g, '_');
        const presignResponse = await fetch(
            `/api/v1/oss/presign?filename=${encodeURIComponent(filename)}`
        );

        if (!presignResponse.ok) {
            throw new Error('获取上传地址失败');
        }

        const presignData = await presignResponse.json();
        if (!presignData.uploadUrl) {
            throw new Error('上传地址无效');
        }

        const uploadResponse = await fetch(presignData.uploadUrl, {
            method: 'PUT',
            body: file,
            headers: {
                'Content-Type': presignData.contentType,
            },
        });

        if (!uploadResponse.ok) {
            throw new Error('图片上传到 OSS 失败');
        }

        return presignData.accessUrl;
    }

    async sendMessage() {
        const messageInput = document.getElementById('messageInput');
        const message = messageInput.value.trim();

        if (!message && !this.imageUrl) {
            alert('请输入消息或上传图片');
            return;
        }

        if (this.isUploading) {
            alert('图片正在上传，请稍候');
            return;
        }

        if (this.isLoading) return;

        this.isLoading = true;
        this.setLoading(true);

        const imageForMessage = this.imageUrl || this.imagePreviewUrl;
        this.addMessage('user', message, imageForMessage);
        messageInput.value = '';

        let typingElement = this.addMessage('assistant', '', null, true);

        try {
            const response = await fetch('/api/v1/chat/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    image_url: this.imageUrl,
                    thread_id: this.threadId,
                }),
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || '请求失败');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let assistantMessage = '';
            let messageElement = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                if (!chunk) continue;

                assistantMessage += chunk;

                if (typingElement) {
                    typingElement.remove();
                    typingElement = null;
                }

                if (!messageElement) {
                    messageElement = document.createElement('div');
                    messageElement.className = 'message assistant';
                    messageElement.innerHTML = '<div class="message-content"></div>';
                    document.getElementById('messageList').appendChild(messageElement);
                }

                messageElement.querySelector('.message-content').innerHTML =
                    this.renderMarkdown(this.stripStatusPrefix(assistantMessage));
                this.scrollToBottom();
            }

            const finalText = this.stripStatusPrefix(assistantMessage);
            if (!finalText.trim()) {
                throw new Error('未收到有效响应');
            }
        } catch (error) {
            console.error('发送消息错误:', error);
            if (typingElement) {
                typingElement.remove();
            }
            this.addMessage('assistant', '抱歉，发生错误，请重试。');
        } finally {
            this.isLoading = false;
            this.setLoading(false);
            this.clearSelectedImage();
        }
    }

    addMessage(role, content, imageUrl, isTyping = false) {
        const messageList = document.getElementById('messageList');
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;

        let contentHtml = '';
        
        // 显示图片（用户消息和助手消息都支持）
        if (imageUrl) {
            let imageSrc = '';
            // 处理 File 对象
            if (imageUrl instanceof File) {
                imageSrc = URL.createObjectURL(imageUrl);
            } 
            // 处理字符串 URL
            else if (typeof imageUrl === 'string' && imageUrl.trim()) {
                imageSrc = imageUrl.trim();
            }
            
            if (imageSrc) {
                contentHtml = `<img src="${imageSrc}" class="message-image" alt="图片" />`;
            }
        }
        
        // 显示文本内容（支持 Markdown 格式）
        if (content && content.trim()) {
            contentHtml += `<div class="message-content">${this.renderMarkdown(content.trim())}</div>`;
        }

        if (isTyping) {
            contentHtml = '<div class="typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>';
        }

        messageDiv.innerHTML = contentHtml;
        messageList.appendChild(messageDiv);
        this.scrollToBottom();

        return messageDiv;
    }

    // Markdown 渲染：块级解析 + 行内样式
    renderMarkdown(text) {
        const blocks = this.parseMarkdownBlocks(text.trim());
        return blocks.join('\n');
    }

    parseMarkdownBlocks(text) {
        const lines = text.split('\n');
        const html = [];
        let i = 0;

        while (i < lines.length) {
            const line = lines[i];

            if (!line.trim()) {
                i += 1;
                continue;
            }

            // 代码块
            if (line.trim().startsWith('```')) {
                const fence = line.trim().slice(3).trim();
                const codeLines = [];
                i += 1;
                while (i < lines.length && !lines[i].trim().startsWith('```')) {
                    codeLines.push(lines[i]);
                    i += 1;
                }
                i += 1;
                html.push(`<pre><code>${this.escapeHtml(codeLines.join('\n'))}</code></pre>`);
                continue;
            }

            // 表格（GFM）
            if (this.isTableRow(line)) {
                const tableLines = [];
                while (i < lines.length && this.isTableRow(lines[i])) {
                    tableLines.push(lines[i]);
                    i += 1;
                }
                html.push(this.renderTable(tableLines));
                continue;
            }

            // 分隔线
            if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
                html.push('<hr/>');
                i += 1;
                continue;
            }

            // 标题
            const heading = line.match(/^(#{1,6})\s+(.+)$/);
            if (heading) {
                const level = heading[1].length;
                html.push(`<h${level}>${this.renderInlineMarkdown(heading[2])}</h${level}>`);
                i += 1;
                continue;
            }

            // 引用
            if (line.trim().startsWith('>')) {
                const quoteLines = [];
                while (i < lines.length && lines[i].trim().startsWith('>')) {
                    quoteLines.push(lines[i].trim().replace(/^>\s?/, ''));
                    i += 1;
                }
                html.push(`<blockquote>${this.renderInlineMarkdown(quoteLines.join('\n'))}</blockquote>`);
                continue;
            }

            // 无序列表：行首 * / - / + 渲染为圆点列表（允许前导空格）
            if (this.isUnorderedListItem(line)) {
                const items = [];
                while (i < lines.length) {
                    if (this.isUnorderedListItem(lines[i])) {
                        items.push(this.getUnorderedListItemContent(lines[i]));
                        i += 1;
                        continue;
                    }
                    // 列表项之间允许空一行
                    if (!lines[i].trim() && i + 1 < lines.length && this.isUnorderedListItem(lines[i + 1])) {
                        i += 1;
                        continue;
                    }
                    break;
                }
                html.push(`<ul>${items.map(item => `<li>${this.renderInlineMarkdown(item)}</li>`).join('')}</ul>`);
                continue;
            }

            // 有序列表：至少连续 2 行才视为列表，避免把 "1. 标题" 误判为 ol
            if (this.isOrderedListItem(line)) {
                const sectionTitle = line.trim();
                const items = [];
                while (i < lines.length) {
                    if (this.isOrderedListItem(lines[i])) {
                        items.push(this.getOrderedListItemContent(lines[i]));
                        i += 1;
                        continue;
                    }
                    if (!lines[i].trim() && i + 1 < lines.length && this.isOrderedListItem(lines[i + 1])) {
                        i += 1;
                        continue;
                    }
                    break;
                }
                if (items.length >= 2) {
                    html.push(`<ol>${items.map(item => `<li>${this.renderInlineMarkdown(item)}</li>`).join('')}</ol>`);
                } else {
                    html.push(`<p class="md-section-title">${this.renderInlineMarkdown(sectionTitle)}</p>`);
                }
                continue;
            }

            // 分类小标题，如「蛋白质类：」
            if (this.isCategoryHeading(line, lines[i + 1])) {
                html.push(`<p class="md-category">${this.renderInlineMarkdown(line.trim())}</p>`);
                i += 1;
                continue;
            }

            // 普通段落（合并连续非空行）
            const paraLines = [];
            while (
                i < lines.length &&
                lines[i].trim() &&
                !this.isTableRow(lines[i]) &&
                !lines[i].trim().startsWith('```') &&
                !/^(#{1,6})\s+/.test(lines[i].trim()) &&
                !/^(-{3,}|\*{3,}|_{3,})$/.test(lines[i].trim()) &&
                !lines[i].trim().startsWith('>') &&
                !this.isUnorderedListItem(lines[i]) &&
                !this.isOrderedListItem(lines[i]) &&
                !this.isCategoryHeading(lines[i], lines[i + 1])
            ) {
                paraLines.push(lines[i]);
                i += 1;
            }
            html.push(`<p>${this.renderInlineMarkdown(paraLines.join('\n'))}</p>`);
        }

        return html;
    }

    isUnorderedListItem(line) {
        return /^\s*[\*\-+•]\s+/.test(line);
    }

    getUnorderedListItemContent(line) {
        return line.replace(/^\s*[\*\-+•]\s+/, '');
    }

    isOrderedListItem(line) {
        return /^\s*\d+\.\s+/.test(line);
    }

    getOrderedListItemContent(line) {
        return line.replace(/^\s*\d+\.\s+/, '');
    }

    isCategoryHeading(line, nextLine) {
        const trimmed = line.trim();
        if (!trimmed || this.isUnorderedListItem(line) || this.isOrderedListItem(line)) {
            return false;
        }
        if (!/[：:]$/.test(trimmed)) {
            return false;
        }
        return nextLine !== undefined && this.isUnorderedListItem(nextLine);
    }

    isTableRow(line) {
        const trimmed = line.trim();
        return trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.includes('|');
    }

    isTableSeparator(line) {
        const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
        const cells = trimmed.split('|').map(cell => cell.trim());
        return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
    }

    parseTableRow(line) {
        const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
        return trimmed.split('|').map(cell => cell.trim());
    }

    renderTable(tableLines) {
        if (tableLines.length < 2) {
            return `<p>${this.renderInlineMarkdown(tableLines.join('\n'))}</p>`;
        }

        let headerCells = this.parseTableRow(tableLines[0]);
        let bodyStart = 1;

        if (this.isTableSeparator(tableLines[1])) {
            bodyStart = 2;
        }

        const bodyRows = tableLines.slice(bodyStart).map(row => this.parseTableRow(row));
        const colCount = headerCells.length;

        const normalizeCells = (cells) => {
            const result = cells.slice(0, colCount);
            while (result.length < colCount) {
                result.push('');
            }
            return result;
        };

        headerCells = normalizeCells(headerCells);

        const thead = `<thead><tr>${headerCells
            .map(cell => `<th>${this.renderInlineMarkdown(cell)}</th>`)
            .join('')}</tr></thead>`;

        const tbody = bodyRows.length
            ? `<tbody>${bodyRows
                  .map(cells => {
                      const normalized = normalizeCells(cells);
                      return `<tr>${normalized
                          .map(cell => `<td>${this.renderInlineMarkdown(cell)}</td>`)
                          .join('')}</tr>`;
                  })
                  .join('')}</tbody>`
            : '';

        return `<div class="md-table-wrapper"><table class="md-table">${thead}${tbody}</table></div>`;
    }

    renderInlineMarkdown(text) {
        let html = this.escapeHtml(text);

        // 图片 ![alt](url)
        html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="md-image" loading="lazy" />');

        // 链接 [text](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

        // 行内代码
        html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');

        // 粗体 **text**
        html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');

        // 斜体 *text* 或 _text_（避免匹配列表标记）
        html = html.replace(/(?<![\\\*])\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
        html = html.replace(/(?<!\\)_([^_\n]+)_/g, '<em>$1</em>');

        // 换行
        html = html.replace(/\n/g, '<br/>');

        return html;
    }

    stripStatusPrefix(text) {
        const prefix = '🔍 正在搜索食谱，请稍候...\n\n';
        if (text.startsWith(prefix) && text.length > prefix.length) {
            return text.slice(prefix.length);
        }
        return text;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollToBottom() {
        const messageList = document.getElementById('messageList');
        messageList.scrollTop = messageList.scrollHeight;
    }

    setLoading(loading) {
        const sendBtn = document.getElementById('sendBtn');
        sendBtn.disabled = loading || this.isUploading;
    }

    async loadHistory() {
        try {
            const response = await fetch(`/api/v1/chat/messages?thread_id=${this.threadId}`);
            const data = await response.json();

            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(msg => {
                    this.addMessage(msg.role, msg.content, msg.image_url);
                });
            }
        } catch (error) {
            console.error('加载历史消息失败:', error);
        }
    }

    async clearChat() {
        if (!confirm('确定要清空对话吗？')) return;

        try {
            await fetch(`/api/v1/chat/messages?thread_id=${this.threadId}`, {
                method: 'DELETE',
            });

            this.threadId = 'thread_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('chat_thread_id', this.threadId);
            document.getElementById('messageList').innerHTML = '';
            this.clearSelectedImage();
        } catch (error) {
            console.error('清空对话失败:', error);
            alert('清空对话失败');
        }
    }
}

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    new ChatApp();
});