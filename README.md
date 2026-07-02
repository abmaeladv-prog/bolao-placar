# Bolão Copa 2026 — atualizador de placar (nuvem)

Roda de graça no GitHub Actions e atualiza o placar do bolão no Firebase,
buscando os jogos da Copa na API pública da ESPN (sem chave).

- `atualizar_placar.py` — o script (só usa a biblioteca padrão do Python).
- `.github/workflows/placar.yml` — agenda a execução a cada ~5 minutos.

Não há segredos aqui: a fonte (ESPN) é pública e as regras do Firebase já
são abertas. O placar oficial para premiação é sempre o do jogo **encerrado**.
