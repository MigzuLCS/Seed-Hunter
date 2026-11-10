# Seed Hunter: guia para agentes de IA

Ferramenta pessoal em Python (so biblioteca padrao) que pre-visualiza seeds de Minecraft Java 26.3 em 3D para comparar
mundos. Leia o `README.md` para uso e preparacao; este arquivo e o que um agente precisa saber para mexer sem quebrar.

## O que ela faz (funil)

```
cubiomes (triagem, sem gerar) -> Paper+Chunky (gera) -> terrain.py (mede relevo) -> juiz de imagem -> BlueMap
```

1. `triagem.py` + `shcubiomes.py` (DLL em `native/`): pontua anel/bacia de montanhas so pela seed (~3 seeds/s com 8 processos).
2. `seed_hunter.py` gera o mundo com um Paper headless (stdin/stdout) e o Chunky, centrado no anel, raio adaptativo.
3. `terrain.py` le os `.mca` e calcula o score de relevo e a neve **medida**.
4. Juiz de imagem (um modelo de visao) da nota 0 a 10 ao mapa de relevo (`docs/juiz-prompt.md`). `--aprovar` leva nota >= 7 ao BlueMap.
5. `ui/` (HTML/CSS/JS puros) e a biblioteca e o inspetor, servidos junto do BlueMap em http://localhost:8100/ui/.

Alvos: `--tipo anel` (interior em terra) e `--tipo bacia` (aceita lago de cratera). `--neve-min F` exige neve medida na crista.

## Comandos

```
python -m unittest discover -s tests          # 32 testes; os do cubiomes pulam sem a DLL
python seed_hunter.py --garimpar 12 --amostra 5000 --tipo bacia --neve-min 0.6
python seed_hunter.py --juiz-preparar         # monta lotes de imagens; o juiz responde um JSON
python seed_hunter.py --juiz-aplicar RESPOSTA.json LOTE
python seed_hunter.py --aprovar --neve-min 0.6
python seed_hunter.py --reindex               # reconstroi bluemap/web/ui/index.json
```

Um `--garimpar` de 5.000 seeds leva ~28 min mais ~10 min de geracao: rode em segundo plano e nao refaca a triagem
se ela ja terminou (a lista das melhores fica no log).

## Regras e cuidados

- **Nunca versione** jars, mundos, `resultados*`, `seeds.txt`, `tools/`, `native/*.dll`: estao no `.gitignore` e o
  projeto nao distribui arquivos do jogo. Nao inclua imagens de terceiros (`referencia/`).
- **EULA:** o usuario aceita a EULA da Mojang e o `accept-download` do BlueMap ele mesmo. Nao aceite por ele.
- **Saves do usuario:** `--jogar` copia para `%APPDATA%\.minecraft\saves\SeedHunter_<seed>`. Nunca mexa em outros saves.
- **Codigo de terceiros:** o `tools/cubiomes` (fork xpple, MIT) e compilado localmente por `native/build.ps1`; confira antes de compilar.
- **Neve:** confie na neve **medida** (`resultados/relevo/*.json`), nao na flag `neve` do juiz (ele ja confundiu rocha nua com neve).
- O CSV `resultados.csv` e a fonte da verdade (ultima linha de cada seed vale). Estados finais: ok, reprovada, sem relevo, candidata, descartada.
- Reinicie o servidor do BlueMap (`-w`) depois de adicionar ou remover mapas; ele so serve o que existia ao subir.
- Windows/PowerShell: aspas aninhadas quebram; use scripts `.ps1` ou arquivos de mensagem (`git commit -F`).
- Mensagens de commit e documentacao em portugues (pt-BR), sem acentos nos identificadores do codigo.

## Mapa do codigo

| Arquivo | Papel |
|---|---|
| `seed_hunter.py` | CLI e pipeline (Paper, Chunky, BlueMap, CSV, juiz, `--jogar`) |
| `terrain.py` | le o mundo (NBT/anvil), `ring_score`, imagem de relevo, `TIPOS` |
| `triagem.py` | etapa 0 com o cubiomes, raio adaptativo |
| `shcubiomes.py`, `native/` | binding ctypes e a DLL (MSVC) |
| `ui/` | biblioteca e inspetor (vanilla JS) |
| `tests/` | `unittest`, sem dependencias |
