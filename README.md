# Teraps

Teraps e um assistente pessoal de inteligencia artificial com interface de holograma feminino, memoria local, fala opcional, microfone opcional, pesquisa na internet, diagnostico interno do sistema, automacoes proativas, lembretes locais e abertura/vinculo de aplicativos no Windows.

A voz do Teraps usa a saida padrao de audio do Windows. Se voce mudar a saida do sistema para fone, caixa, HDMI ou Bluetooth, a fala acompanha essa configuracao.

A interface nao depende de botoes de comando: digite e pressione `Enter`; use `Ctrl+Espaco` ou duplo clique no campo de entrada para falar pelo microfone padrao do Windows.

## Como executar

```powershell
python teraps.py
```

Ou use o executador unico:

```powershell
.\Teraps.bat
```

O programa roda sem dependencias obrigatorias usando Python e Tkinter. Para ativar voz feminina local e entrada por microfone, instale os opcionais:

```powershell
python -m pip install -r requirements-optional.txt
```

Tambem existe um instalador auxiliar:

```powershell
powershell -ExecutionPolicy Bypass -File .\instalar_opcionais.ps1
```

Para gerar um `.exe` unico:

```powershell
powershell -ExecutionPolicy Bypass -File .\criar_executavel.ps1
```

## Comandos uteis

- `ajuda`
- `central comandos`
- `modo completo`
- `status completo`
- `teste unreal fala`
- `status github`
- `checklist release`
- `pesquise noticias de tecnologia`
- `abra calculadora`
- `abra bloco de notas`
- `vincule photoshop em "C:\Caminho\Photoshop.exe"`
- `apps vinculados`
- `lembre que eu prefiro respostas curtas`
- `o que voce lembra`
- `sistema`
- `terminal interno`
- `telas integradas`
- `painel sistema`
- `painel memoria`
- `autodiagnostico`
- `autorreparo`
- `comando ipconfig`
- `comando tarefas`
- `comando disco`
- `me lembre de revisar o projeto as 18:30`
- `lembretes`
- `automacao proativa`
- `ativar voz`
- `desativar voz`
- `saida de audio`
- `teste voz`
- `hora`
- `data`
- `sugestoes`
- `ajuda trabalho`
- `plano trabalho minha profissao`
- `produtividade minha area`
- `rotina profissional minha area`
- `checklist servico minha area`
- `melhorar vida`
- `diagnostico produtividade`
- `voz teraps`
- `voz neural`
- `voz windows`
- `status voz`
- `status microfone`
- `configurar canal youtube Nome | @handle ou UC... | email | nicho | publico alvo`
- `canal youtube`
- `criar video youtube tema do video`
- `calendario youtube`
- `conteudos youtube`
- `configurar youtube api "C:\Caminho\client_secret.json"`
- `modo foco`
- `status git`
- `pipelines`
- `ajuda programador`
- `ajuda designer`
- `plano app minha ideia`
- `arquitetura projeto minha ideia`
- `stack projeto minha ideia`
- `revisar codigo teraps.py`
- `explicar codigo teraps.py`
- `checklist deploy`
- `design system Teraps`
- `ux review tela principal`
- `briefing design Teraps`
- `start day`
- `wind down`
- `resumo executivo`
- `sensores`
- `configurar workspace "C:\Projeto"`
- `configurar ide code`
- `configurar home assistant http://localhost:8123/api TOKEN`
- `ponte 3d`
- `iniciar unreal`
- `status unreal`
- `configurar unreal "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"`
- `aprendizado automatico`
- `estado automatico`
- `verificar atualizacao`
- `configurar fonte update URL`
- `manutencao automatica`

## Arquitetura

- `teraps.py`: executador unico com UI, holograma, voz, memoria, pesquisa e automacao.
- Avatar visual com estados de repouso, escuta, processamento e conversa com painel holografico.
- Avatar renderizado em PNG com animacoes de brilho, varredura, flutuacao, particulas e painel.
- Automacao de workspace: modo foco, Git, pipeline local e abertura de IDE.
- Smart home: cenas simuladas por padrao ou Home Assistant quando configurado.
- Rotinas: resumo executivo, inicio do dia, descanso noturno e sensores ambientais.
- Avatar Unreal Engine: projeto em `unreal/TerapsHologram` com cena holografica 3D, materiais translucidos, particulas orbitais, olhos/pupilas/boca 3D, gestos, microexpressoes e ponte TCP local para receber estados, texto e duracao de fala do Teraps.
- Ponte 3D opcional: envia estado para renderizador externo quando ativada; o renderizador Unreal usa `127.0.0.1:8765`.
- Aprendizado automatico: consolida preferencias, temas, sugestoes e estado do programa no SQLite.
- Aprendizado pessoal automatico: entende frases como `eu gosto de...`, `prefiro...`, `trabalho com...` e salva isso sem precisar usar `lembre que`.
- Lembretes e tarefas locais: grava lembretes no SQLite e avisa dentro da propria conversa quando vencem.
- Executor interno oculto: comandos de diagnostico rodam como filhos invisiveis do `.exe`; a saida aparece no chat, sem abrir terminal externo.
- Interface integrada: conversa, terminal interno, painel de sistema e memoria/aprendizado ficam juntos dentro da janela do `.exe`.
- Central de comandos: atalhos unificados para tudo que foi integrado no Teraps, incluindo voz, microfone, avatar Unreal, aprendizado, YouTube, tecnologia, trabalho, automacao, GitHub e release.
- Entrada por voz: usa o microfone padrao definido no Windows, reconhece a fala e executa o comando como texto normal. Se nao entender, pede para o usuario explicar de outro jeito.
- Tech Studio: ajuda programadores, desenvolvedores e designers com planejamento de apps, arquitetura, stack, revisao rapida de codigo, explicacao de arquivos, checklist de deploy, design system, UX review e briefing de design.
- Life & Work Studio: ajuda em areas amplas de emprego, servicos e vida pessoal com planos de produtividade, rotinas, checklists, melhorias de tempo, atendimento, vendas, administracao, saude, educacao, financeiro, juridico, logistica, criacao, operacoes, seguranca e servicos locais.
- Criador YouTube: configura conta/canal, salva perfil do canal no SQLite, gera ideias, titulos, descricoes, tags, roteiros, checklist e calendario editorial.
- Administracao YouTube preparada: guarda caminho de credenciais OAuth/API e deixa o sistema pronto para YouTube Data API oficial. Upload/alteracao real do canal exige autorizacao da conta Google.
- Automacao proativa: verifica periodicamente lembretes, perfil aprendido, manutencao, atualizacoes e sugestoes de rotina.
- Atualizacao automatica: registra verificacoes locais/remotas quando uma fonte de update e configurada.
- Manutencao automatica: otimiza o banco e limita historicos internos sem apagar memoria importante.
- `Teraps.bat`: atalho unico para iniciar no Windows.
- `instalar_opcionais.ps1`: instala recursos extras quando o hardware/sistema permitir.
- `criar_executavel.ps1`: gera `dist\Teraps.exe` com PyInstaller.
- `assets/teraps.ico`: icone da janela e do executavel.
- `assets/teraps_icon_avatar.png`: versao PNG do icone baseada no avatar.
- `unreal/TerapsHologram/TerapsHologram.uproject`: projeto Unreal Engine para o avatar 3D.
- `unreal/TerapsHologram/Content/Python/teraps_unreal_bridge.py`: script que cria a cena 3D e recebe comandos do Teraps.
- `teraps_data/memory.sqlite3`: banco principal com memoria, historico, configuracoes, sugestoes, lembretes, automacoes, conteudos YouTube e aprendizado de temas.
- `teraps_data/config.json`: arquivo antigo, importado automaticamente quando existir; a configuracao ativa fica no SQLite.
- `teraps_data/teraps.log`: registro de erros e diagnosticos.

## Perfis de hardware

O Teraps detecta automaticamente o hardware e ajusta FPS, brilho e particulas. Tambem e possivel editar `teraps_data/config.json`:

```json
{
  "profile": "eco"
}
```

Valores aceitos: `auto`, `eco`, `ultra`.

## Observacao importante

Esta e uma base original e funcional, nao uma copia de uma IA existente. Ela nao promete consciencia nem inteligencia geral perfeita. O objetivo e entregar um nucleo proprio, extensivel e leve, que pode ganhar conectores, modelos locais, agenda, automacoes mais profundas e atualizacoes assinadas em proximas versoes.
