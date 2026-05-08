# Shopee Dashboard PWA

Dashboard profissional de afiliados Shopee, instalável no celular como app.

## Estrutura

```
├── api/
│   └── shopee.py          ← backend Python (Vercel Serverless)
├── static/
│   ├── index.html         ← interface PWA
│   ├── manifest.json      ← configuração PWA
│   └── sw.js              ← service worker
├── vercel.json            ← configuração Vercel
└── requirements.txt
```

## Deploy

### 1. Criar repositório no GitHub
Suba todos os arquivos em um repositório **privado**.

### 2. Conectar no Vercel
- Acesse [vercel.com](https://vercel.com)
- Clique em **Add New → Project**
- Importe o repositório do GitHub
- Clique em **Deploy**

### 3. Configurar Secrets no Vercel
Após o deploy, vá em:
`Settings → Environment Variables`

| Nome            | Valor              |
|-----------------|--------------------|
| `SHOPEE_APP_ID` | seu AppID          |
| `SHOPEE_SECRET` | seu Secret         |

Após adicionar as variáveis, clique em **Redeploy**.

### 4. Instalar no celular
- Abra a URL do app no Chrome (Android) ou Safari (iOS)
- Android: menu → **Adicionar à tela inicial**
- iOS: botão compartilhar → **Adicionar à tela de início**

## Funcionalidades

- 📅 Filtro por data (padrão = dia anterior)
- 🔍 Busca por sub_id
- 💰 Total de comissões
- 📦 Total de pedidos
- 🏆 Ranking por comissão
- 📋 Toque para copiar sub_id
- 📱 Instalável como PWA
