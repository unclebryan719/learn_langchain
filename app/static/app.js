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

    // Markdown 渲染函数
    renderMarkdown(text) {
        // 转义 HTML
        let html = this.escapeHtml(text);
        
        // 处理分隔线
        html = html.replace(/^---$/gm, '<hr/>');
        
        // 处理标题
        html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
        
        // 处理无序列表
        html = html.replace(/^[\*\-] (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*?<\/li>)/gs, '<ul>$1</ul>');
        
        // 处理有序列表
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
        
        // 处理粗体
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        
        // 处理斜体
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        
        // 处理引用
        html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
        
        // 处理代码（行内）
        html = html.replace(/`(.+?)`/g, '<code>$1</code>');
        
        // 处理代码块
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        
        // 处理链接
        html = html.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank">$1</a>');
        
        // 处理换行
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