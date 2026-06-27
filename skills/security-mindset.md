---
name: security-mindset
trigger: 安全, security, 输入校验, 认证, 授权, 加密, 注入, OWASP
priority: high
---

# Skill: Security Mindset

默认怀疑一切外部输入。OWASP Top 10 检查。最小权限原则。

## 核心原则

1. **永远不信任输入**：用户输入、外部 API、文件内容、URL 参数都必须校验
2. **最小权限**：只给必要的权限，能用低权限就别用高权限
3. **纵深防御**：多层防护，单层失效不致命
4. **失败安全**：异常时拒绝访问，不默认放行
5. **不暴露细节**：错误信息不泄漏内部结构、堆栈、版本号

## OWASP Top 10 检查清单

### A1 失效的访问控制
- [ ] 每个接口都有权限校验？
- [ ] 水平越权：用户 A 能否访问用户 B 的资源？
- [ ] 垂直越权：普通用户能否调用管理员接口？
- [ ] 直接对象引用：URL 中的 id 是否校验归属？

### A2 加密失败
- [ ] 传输用 HTTPS？
- [ ] 密码用 bcrypt/scrypt/argon2 哈希？禁止 MD5/SHA1
- [ ] 敏感数据（Token/密钥）加密存储？
- [ ] 不在日志/响应中泄漏敏感信息？

### A3 注入
- [ ] SQL 用参数化查询？禁止字符串拼接
- [ ] 命令执行用参数列表，不用 shell=True
- [ ] 模板渲染自动转义？Jinja2 autoescape
- [ ] 路径校验：`os.path.realpath` + 白名单

### A4 不安全设计
- [ ] 关键操作有速率限制？
- [ ] 一次性 token 用完即失效？
- [ ] CSRF 防护：双提交 Cookie / SameSite
- [ ] 重放攻击：nonce / 时间戳

### A5 安全配置错误
- [ ] 默认凭据改掉？
- [ ] 调试模式关闭？
- [ ] 错误页面不泄漏堆栈？
- [ ] 不必要的功能/接口关闭？

### A6 易受攻击的组件
- [ ] 依赖定期更新？
- [ ] 已知 CVE 漏洞修复？
- [ ] 锁定依赖版本？

### A7 认证失败
- [ ] 密码强度策略？
- [ ] 登录失败锁定？
- [ ] 会话固定攻击防护？
- [ ] Session 超时？

### A8 软件和数据完整性
- [ ] CI/CD 流水线可信？
- [ ] 第三方库来源可信？
- [ ] 关键数据有签名/校验？

### A9 日志监控失败
- [ ] 关键操作有审计日志？
- [ ] 日志不包含敏感信息？
- [ ] 异常行为告警？

### A10 服务端请求伪造（SSRF）
- [ ] 外部 URL 请求校验白名单？
- [ ] 禁止访问内网（127.0.0.1/10.0.0.0/8/192.168.0.0/16）？
- [ ] DNS rebinding 防护？

## 常见注入场景

### SQL 注入
```python
# 禁止
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# 正确
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

### 命令注入
```python
# 禁止
os.system(f"ls {user_dir}")
subprocess.run(f"ls {user_dir}", shell=True)

# 正确
subprocess.run(["ls", user_dir], shell=False)
```

### 路径遍历
```python
# 禁止
with open(f"/data/{filename}") as f:
    ...

# 正确
base = os.path.realpath("/data")
real_path = os.path.realpath(os.path.join(base, filename))
if not real_path.startswith(base + os.sep):
    raise ValueError("path traversal detected")
```

### XSS
```python
# 禁止：直接渲染用户输入到 HTML
return f"<div>{user_input}</div>"

# 正确：HTML 转义
import html
return f"<div>{html.escape(user_input)}</div>"
```

## 输入校验模板

```python
from pydantic import BaseModel, validator

class UserInput(BaseModel):
    name: str
    age: int
    email: str

    @validator("name")
    def validate_name(cls, v):
        if len(v) > 100 or len(v) < 1:
            raise ValueError("name length must be 1-100")
        if not v.isprintable():
            raise ValueError("name must be printable")
        return v

    @validator("age")
    def validate_age(cls, v):
        if not 0 <= v <= 150:
            raise ValueError("age must be 0-150")
        return v
```

## 输出格式

发现安全问题时：

```
🚨 安全问题（严重程度：高/中/低）
【位置】<file:line>
【类型】OWASP A<x>: <类别>
【风险】<具体风险描述>
【修复】<具体修复方案 + 代码示例>
```

## 禁止行为

- 禁止把用户输入直接拼接到 SQL/命令/HTML
- 禁止 catch 异常后默认放行
- 禁止在生产环境开 debug 模式
- 禁止把密钥/Token 硬编码或提交到 git
- 禁止用 MD5/SHA1 哈希密码
- 禁止忽略安全告警
