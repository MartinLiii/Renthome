from flask import Flask, render_template, request, redirect, url_for, session, abort
import sqlite3
import os
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = '123456'

# =========================
# 📁 上传文件配置
# =========================
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# =========================
# 🧠 数据库
# =========================
def get_db():
    return sqlite3.connect('data.db')


def init_db():
    conn = get_db()
    c = conn.cursor()

    # 用户表：添加头像、简介、创建时间
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        avatar TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 帖子表：扩展字段支持点赞、标签、多图
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY,
        user TEXT,
        title TEXT,
        content TEXT,
        images TEXT,
        category TEXT DEFAULT 'other',
        likes_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user) REFERENCES users(username)
    )''')

    # 点赞表：记录谁点赞了哪个帖子
    c.execute('''CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY,
        user TEXT,
        post_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user, post_id),
        FOREIGN KEY(post_id) REFERENCES posts(id)
    )''')

    # 评论表
    c.execute('''CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY,
        user TEXT,
        post_id INTEGER,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(post_id) REFERENCES posts(id)
    )''')

    # 关注表
    c.execute('''CREATE TABLE IF NOT EXISTS follows (
        id INTEGER PRIMARY KEY,
        follower TEXT,
        following TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(follower, following)
    )''')

    # 消息表：优化支持时间戳和已读状态
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        sender TEXT,
        receiver TEXT,
        content TEXT,
        image TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 保留旧版friends表兼容
    c.execute('CREATE TABLE IF NOT EXISTS friends (id INTEGER PRIMARY KEY, user TEXT, friend TEXT)')

    conn.commit()
    conn.close()


# =========================
# 🔐 登录保护装饰器
# =========================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return wrapper


# =========================
# 🏠 Home / Feed
# =========================
@app.route('/')
def home():
    category = request.args.get('category', '')

    conn = get_db()
    c = conn.cursor()

    # Build query with optional category filter
    if category:
        query = """
            SELECT p.id, p.user, p.title, p.content, p.images, p.category,
                   p.likes_count, p.created_at,
                   (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count
            FROM posts p
            WHERE p.category = ?
            ORDER BY p.created_at DESC
        """
        c.execute(query, (category,))
    else:
        query = """
            SELECT p.id, p.user, p.title, p.content, p.images, p.category,
                   p.likes_count, p.created_at,
                   (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count
            FROM posts p
            ORDER BY p.created_at DESC
        """
        c.execute(query)

    posts = c.fetchall()

    # Get posts liked by current user
    liked_posts = set()
    if 'user' in session:
        c.execute("SELECT post_id FROM likes WHERE user=?", (session['user'],))
        liked_posts = {row[0] for row in c.fetchall()}

    conn.close()
    return render_template('home_new.html', posts=posts, liked_posts=liked_posts)


# =========================
# 📝 注册
# =========================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username=?", (username,))
        if c.fetchone():
            return "Username exists"

        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        conn.close()

        return redirect('/login')

    return render_template('register_new.html')


# =========================
# 🔑 登录（修复版：不存在→去注册）
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()

        # ❌ 用户不存在 → 去注册
        if not user:
            return redirect('/register')

        # ❌ 密码错误
        if user[2] != password:
            return "Wrong password"

        # ✅ 登录成功
        session['user'] = username
        return redirect('/')

    return render_template('login_new.html')


# =========================
# 📝 发帖（支持多图 + 标签）
# =========================
@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():

    if request.method == 'POST':

        title = request.form['title']
        content = request.form['content']
        category = request.form.get('category', 'other')

        # 支持多图上传，用逗号分隔
        image_paths = []
        files = request.files.getlist('images')
        for f in files:
            if f and f.filename != '':
                filename = secure_filename(f.filename)
                # 添加时间戳防止文件名冲突
                import time
                filename = f"{int(time.time())}_{filename}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                f.save(save_path)
                image_paths.append('uploads/' + filename)

        images_str = ','.join(image_paths) if image_paths else ''

        conn = get_db()
        c = conn.cursor()

        c.execute("""
            INSERT INTO posts (user, title, content, images, category)
            VALUES (?, ?, ?, ?, ?)
        """, (session['user'], title, content, images_str, category))

        conn.commit()
        conn.close()

        return redirect('/')

    return render_template('create_new.html')


# =========================
# 👤 个人主页
# =========================
@app.route('/profile')
@login_required
def profile():
    username = request.args.get('user', session['user'])

    conn = get_db()
    c = conn.cursor()

    # 获取用户信息
    c.execute("SELECT username, avatar, bio FROM users WHERE username=?", (username,))
    user_info = c.fetchone()

    # 获取用户帖子
    c.execute("""
        SELECT id, title, content, images, likes_count, created_at,
               (SELECT COUNT(*) FROM comments WHERE post_id = posts.id) as comments_count
        FROM posts WHERE user=? ORDER BY created_at DESC
    """, (username,))
    posts = c.fetchall()

    # 获取粉丝和关注数
    c.execute("SELECT COUNT(*) FROM follows WHERE following=?", (username,))
    followers_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM follows WHERE follower=?", (username,))
    following_count = c.fetchone()[0]

    # 检查当前用户是否关注了该用户
    is_following = False
    if 'user' in session and session['user'] != username:
        c.execute("SELECT 1 FROM follows WHERE follower=? AND following=?",
                  (session['user'], username))
        is_following = c.fetchone() is not None

    conn.close()

    return render_template('profile_new.html',
                          user=username,
                          user_info=user_info,
                          posts=posts,
                          followers_count=followers_count,
                          following_count=following_count,
                          is_following=is_following)


# =========================
# 👍 点赞/取消点赞
# =========================
@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def like(post_id):
    conn = get_db()
    c = conn.cursor()

    # 检查是否已点赞
    c.execute("SELECT 1 FROM likes WHERE user=? AND post_id=?", (session['user'], post_id))
    already_liked = c.fetchone()

    if already_liked:
        # 取消点赞
        c.execute("DELETE FROM likes WHERE user=? AND post_id=?", (session['user'], post_id))
        c.execute("UPDATE posts SET likes_count = likes_count - 1 WHERE id=?", (post_id,))
    else:
        # 添加点赞
        c.execute("INSERT INTO likes VALUES (NULL, ?, ?)", (session['user'], post_id))
        c.execute("UPDATE posts SET likes_count = likes_count + 1 WHERE id=?", (post_id,))

    conn.commit()

    # 获取更新后的点赞数
    c.execute("SELECT likes_count FROM posts WHERE id=?", (post_id,))
    likes_count = c.fetchone()[0]

    conn.close()
    return {'success': True, 'liked': not already_liked, 'likes_count': likes_count}


# =========================
# 💬 评论
# =========================
@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def comment(post_id):
    content = request.form.get('content', '').strip()
    if not content:
        return {'success': False, 'error': '评论不能为空'}

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO comments VALUES (NULL, ?, ?, ?)",
              (session['user'], post_id, content))
    conn.commit()

    # 获取评论数和最新评论
    c.execute("SELECT COUNT(*) FROM comments WHERE post_id=?", (post_id,))
    comments_count = c.fetchone()[0]
    c.execute("""
        SELECT c.user, c.content, c.created_at FROM comments c
        WHERE c.post_id=? ORDER BY c.created_at DESC LIMIT 1
    """, (post_id,))
    latest_comment = c.fetchone()

    conn.close()
    return {
        'success': True,
        'comments_count': comments_count,
        'comment': {'user': latest_comment[0], 'content': latest_comment[1]}
    }


# =========================
# 获取帖子评论
# =========================
@app.route('/comments/<int:post_id>')
@login_required
def get_comments(post_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT c.user, c.content, c.created_at FROM comments c
        WHERE c.post_id=? ORDER BY c.created_at DESC
    """, (post_id,))
    comments = [{'user': row[0], 'content': row[1], 'created_at': row[2]} for row in c.fetchall()]
    conn.close()
    return {'comments': comments}


# =========================
# 👥 关注/取消关注
# =========================
@app.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    if username == session['user']:
        return {'success': False, 'error': '不能关注自己'}

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT 1 FROM follows WHERE follower=? AND following=?",
              (session['user'], username))
    already_following = c.fetchone()

    if already_following:
        c.execute("DELETE FROM follows WHERE follower=? AND following=?",
                  (session['user'], username))
        action = 'unfollowed'
    else:
        c.execute("INSERT INTO follows VALUES (NULL, ?, ?)",
                  (session['user'], username))
        action = 'followed'

    conn.commit()

    # 获取更新后的粉丝数
    c.execute("SELECT COUNT(*) FROM follows WHERE following=?", (username,))
    followers_count = c.fetchone()[0]

    conn.close()
    return {'success': True, 'action': action, 'followers_count': followers_count}


# =========================
# 🏠 首页 - 获取用户关注的帖子
# =========================
@app.route('/following')
@login_required
def following_feed():
    conn = get_db()
    c = conn.cursor()

    # 获取关注用户的帖子
    c.execute("""
        SELECT p.id, p.user, p.title, p.content, p.images, p.category,
               p.likes_count, p.created_at,
               (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count
        FROM posts p
        WHERE p.user IN (SELECT following FROM follows WHERE follower=?)
        ORDER BY p.created_at DESC
    """, (session['user'],))
    posts = c.fetchall()

    # 获取点赞的帖子
    c.execute("SELECT post_id FROM likes WHERE user=?", (session['user'],))
    liked_posts = {row[0] for row in c.fetchall()}

    conn.close()
    return render_template('home_new.html', posts=posts, liked_posts=liked_posts, following_only=True)


# =========================
# 👥 好友（保留兼容）
# =========================
@app.route('/friends', methods=['GET', 'POST'])
@login_required
def friends():

    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        c.execute("INSERT INTO friends VALUES (NULL, ?, ?)",
                  (session['user'], request.form['friend']))
        conn.commit()

    c.execute("SELECT friend FROM friends WHERE user=?", (session['user'],))
    friends = c.fetchall()
    conn.close()

    return render_template('friends_new.html', friends=friends)


# =========================
# 🔍 搜索用户和帖子
# =========================
@app.route('/search')
def search():
    query = request.args.get('q', '')

    if not query:
        return render_template('search.html', users=[], posts=[])

    conn = get_db()
    c = conn.cursor()

    # 搜索用户
    c.execute("SELECT username, avatar, bio FROM users WHERE username LIKE ?",
              (f'%{query}%',))
    users = c.fetchall()

    # 搜索帖子
    c.execute("""
        SELECT p.id, p.user, p.title, p.content, p.images, p.category,
               p.likes_count, p.created_at
        FROM posts p
        WHERE p.title LIKE ? OR p.content LIKE ? OR p.category LIKE ?
        ORDER BY p.created_at DESC
    """, (f'%{query}%', f'%{query}%', f'%{query}%'))
    posts = c.fetchall()

    conn.close()
    return render_template('search.html', users=users, posts=posts, query=query)


# =========================
# 💬 Messages - Get conversation list
# =========================
@app.route('/messages')
@login_required
def messages():
    conn = get_db()
    c = conn.cursor()

    # Get all messages involving current user
    c.execute("""
        SELECT sender, receiver, content, created_at, is_read
        FROM messages
        WHERE sender=? OR receiver=?
        ORDER BY created_at DESC
    """, (session['user'], session['user']))

    all_messages = c.fetchall()

    # Group by conversation partner
    conversations_dict = {}
    for msg in all_messages:
        other = msg[1] if msg[0] == session['user'] else msg[0]
        if other not in conversations_dict:
            conversations_dict[other] = {
                'last_message': msg[2],
                'last_time': msg[3],
                'unread': 0
            }
        if msg[0] == other and msg[4] == 0:
            conversations_dict[other]['unread'] += 1

    # Sort by last time
    sorted_convs = sorted(conversations_dict.items(), key=lambda x: x[1]['last_time'], reverse=True)
    conversations = [(k, v['last_message'], v['last_time'], v['unread']) for k, v in sorted_convs]

    conn.close()
    return render_template('messages.html', conversations=conversations)


# =========================
# 💬 聊天
# =========================
@app.route('/chat/<friend>', methods=['GET', 'POST'])
@login_required
def chat(friend):

    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        image_file = request.files.get('image')
        image_path = None

        if image_file and image_file.filename != '':
            filename = secure_filename(image_file.filename)
            import time
            filename = f"{int(time.time())}_{filename}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            image_path = 'uploads/' + filename

        if content or image_path:
            c.execute("INSERT INTO messages VALUES (NULL, ?, ?, ?, ?)",
                      (session['user'], friend, content, image_path))
            conn.commit()

    # 获取聊天记录
    c.execute("""
        SELECT sender, content, image, created_at FROM messages
        WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)
        ORDER BY created_at ASC
    """, (session['user'], friend, friend, session['user']))

    msgs = c.fetchall()

    # 标记为已读
    c.execute("UPDATE messages SET is_read=1 WHERE sender=? AND receiver=?",
              (friend, session['user']))

    conn.close()

    return render_template('chat_new.html', msgs=msgs, friend=friend)


# =========================
# 🚪 登出
# =========================
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# =========================
# 🚀 启动
# =========================
  if __name__ == '__main__':
      init_db()
      port = int(os.environ.get('PORT', 5000))
      app.run(host='0.0.0.0', port=port, debug=True)
