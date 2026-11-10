# Seed Hunter

> Projeto pessoal em andamento. Funciona na minha máquina; espere arestas.

Transforma uma lista de seeds de Minecraft Java em mapas 3D navegáveis no navegador, sem abrir o jogo. Para cada seed ele filtra com `/locate`, pré-gera 30 chunks (480 blocos) em volta do spawn e renderiza com o BlueMap. Você deixa rodando e volta para comparar.

```
seeds.txt -> Paper headless -> /locate (filtro) -> Chunky (pré-gera) -> BlueMap CLI -> http://localhost:8100
```

Testado com Minecraft Java 26.3, Paper 26.3, Chunky 1.5.66 e BlueMap 5.29 (Java 25).

## Requisitos

- Python 3.10+ (só biblioteca padrão)
- Java 25 (Temurin). O script usa `tools/jdk-25*/` se existir; senão, o `java` do PATH.
- Ter o Minecraft Java: o BlueMap baixa o client da Mojang para as texturas.

## Preparação (uma vez)

Os jars não ficam no repositório. Baixe e coloque assim:

```
server/paper.jar                    # https://papermc.io/downloads/paper (26.3)
server/plugins/Chunky-Paper-*.jar   # https://modrinth.com/project/fALzjamp
bluemap/bluemap-cli.jar             # https://github.com/BlueMap-Minecraft/BlueMap/releases (*-cli.jar, 5.25+)
```

1. Em `server/`, rode `java -jar paper.jar --nogui` uma vez e, **se concordar com a [EULA da Mojang](https://aka.ms/MinecraftEULA)**, troque `eula=false` por `eula=true` em `eula.txt`.
2. Em `bluemap/`, rode `java -jar bluemap-cli.jar` uma vez e, se concordar com a EULA, troque `accept-download: false` por `true` em `config/core.conf`.
3. Copie `seeds.example.txt` para `seeds.txt` e coloque suas seeds (uma por linha, `#` comenta). Ou use `--random N`.

## Uso

```
python seed_hunter.py                      # processa seeds.txt
python seed_hunter.py --random 50          # testa 50 seeds aleatórias
python seed_hunter.py --limit 3 --verbose  # só 3 seeds, com o log do servidor
python seed_hunter.py --rule "structure #minecraft:village=800" --rule "biome minecraft:cherry_grove=1000"
```

Para ver os resultados: `cd bluemap && java -jar bluemap-cli.jar -w` e abra **http://localhost:8100/ui/**.

- **Biblioteca:** miniatura vista de cima de cada seed, tags dos achados, favoritas, filtros e busca.
- **Inspetor:** mapa 3D com menu lateral de estruturas e biomas (clique para voar até o local), modos Perspectiva e Vista de cima, anotações e "Escolher esta seed". "Recolher painel" libera o mapa e o menu do próprio BlueMap (seletor de mapas, distância de render).
- Favoritos, anotações e escolhidas ficam no `localStorage` do navegador.
- O mapa puro do BlueMap continua em http://localhost:8100 (o botão "Abrir no BlueMap" leva para lá).

**Reinicie o servidor (`-w`) depois de gerar seeds novas ou cavernas:** ele só serve os mapas que existiam quando subiu. Se o navegador mostrar "erro ao carregar este mapa" logo depois disso, recarregue com Ctrl+Shift+R (o BlueMap deixa respostas em cache por 24 h).

### Funil de relevo: achar um anel de montanhas antes do BlueMap

Renderizar custa tempo e disco, então o script mede o terreno antes. Para cada seed:

1. **Gera** com o Paper e o Chunky (~1 min). Não há regra de vila por padrão: a vila é só informação. Dá para reativar com `--rule "structure #minecraft:village=480"`.
2. **Mede o relevo** (`terrain.py`, ~8 s): lê os arquivos do mundo e procura um centro mais baixo cercado por uma crista alta em todas as direções (score de 0 a 1). Abaixo de `--anel-min` (0,5) o mundo é apagado na hora (`sem relevo`). O resto vira `candidata`, com uma imagem de relevo vista de cima em `resultados/relevo/`.
3. **Juiz de imagem** (nota de 0 a 10 para "anel de montanhas, de preferência nevadas, com um bioma por dentro"). O score geométrico sozinho dá falsos positivos (planaltos, badlands), então um modelo de visão olha a imagem. Nos testes, o Sonnet acertou e o Haiku errou, então use o Sonnet.
4. **Aprova:** nota ≥ `--nota-min` (7) vai ao BlueMap (`ok`); as outras são `descartada` e o mundo é apagado.

```
python seed_hunter.py --random 24            # passos 1 e 2
python seed_hunter.py --juiz-preparar        # monta lotes de imagens com nomes embaralhados (resultados/juiz/lote_*)
#   o juiz abre img_NN.png de cada lote e devolve {"notas": {"img_01": {"nota": 8, "neve": true, "motivo": "..."}}}
python seed_hunter.py --juiz-aplicar resposta.json resultados/juiz/lote_...
python seed_hunter.py --aprovar              # passo 4
```

As imagens vão sem o score nem a seed, para o juiz não ser influenciado. Na biblioteca, as candidatas aparecem com a imagem de relevo e a nota; "Neve" vira tag. `--sem-anel` desliga o funil (toda seed gerada vai direto ao BlueMap).

### Triagem sem gerar o mundo (Cubiomes, experimental)

O [fork `xpple/cubiomes`](https://github.com/xpple/cubiomes) (MIT) calcula biomas e uma estimativa de altura direto da seed, sem gerar chunks, e já suporta a 26.3. Medido contra os mundos reais do Paper: **99,95% dos biomas iguais** (1,07 milhão de células, 18 mundos) e altura com correlação 0,96. O score de anel calculado só com ele tem ranking com correlação 0,9 em relação ao medido no mundo gerado, em ~0,7 s por seed (contra ~1 min gerando).

```
git clone https://github.com/xpple/cubiomes tools/cubiomes      # fonte de terceiros: confira antes de compilar
powershell -File native/build.ps1                                # gera native/shbiomes.dll (precisa do Visual Studio com C++)
python native/verificar.py                                       # compara biomas do cubiomes com worlds/
python native/anel_cubiomes.py                                   # score de anel so com o cubiomes vs medido
```

O MSVC compila os arquivos de bioma (o README do fork diz que ele não é suportado); o módulo de terreno e a estimativa de spawn (`finders.c`) não compilam nele, então o spawn ainda vem do servidor.

**Etapa 0 do funil (`--garimpar`)**, em vez de `--random`:

```
python seed_hunter.py --garimpar 6 --amostra 600    # avalia 600 seeds só com o cubiomes e gera as 6 melhores
```

1. `triagem.py` avalia o anel de `--amostra` seeds aleatórias em paralelo e fica com as `N` de maior score (mínimo `--triagem-min`, 0,4: o score só-cubiomes fica uns 30% abaixo do medido no mundo). A janela avaliada tem **720 blocos de raio** em volta de (0,0) e procura anéis de **até 300 blocos de raio** (`CHUNKS` e `RMAX` em `triagem.py`). Custo medido: ~3 seeds/s com 8 processos (a janela de 480 blocos fazia ~8/s).
2. O Chunky gera **em volta do centro do anel** (e não do spawn), com **raio adaptativo**: raio do anel + 160 blocos, entre 320 e 960 (`adaptive_radius`). Um anel pequeno gera menos que os 480 fixos (menos tempo e disco), e um anel grande ganha o que precisa. O spawn pode ficar fora da área gerada; o jogo gera o resto normalmente ao jogar. O centro, o raio e a triagem ficam gravados no JSON da seed.
3. O resto do funil é o mesmo: análise de relevo no mundo gerado, juiz de imagem e `--aprovar`.

Na rodada de teste, as 6 melhores de 600 deram score de relevo de 0,75 a 0,85 no mundo gerado e o cubiomes previu valores próximos (0,70 a 0,82). Já 24 seeds aleatórias sem triagem renderam só 4 candidatas, com máximo de 0,74.

Com a janela de 720 e o raio adaptativo (400 seeds em 124 s, 4 geradas): raios de geração de 320 a 424 blocos, 0,6 a 0,9 min e 30 a 57 MB por seed (contra ~1 min e ~60 MB com 480 fixos). **Cuidado:** anéis maiores dão mais falsos positivos, porque há mais combinações de centro e raio. O melhor da rodada (score 0,80, anel de ~264 blocos) é visualmente um lago num vale com picos nevados soltos, não um anel; o juiz de imagem continua sendo o filtro final.

**Outros alvos (`--tipo bacia`).** Por padrao o interior do anel precisa ser terra (`--tipo anel`). Com `--tipo bacia` a triagem aceita um interior abaixo do nivel do mar, ou seja, um **lago de cratera cercado de penhascos** (por exemplo, um lago congelado em volta de neve). O Cubiomes ignora a agua que enche a bacia, entao a triagem limita o interior ao nivel do mar (`SEA_LEVEL`) para o desnivel bater com o mundo real. Teste: a seed de um video de "fase de Natal" (`-123456793079414942`) pontua 0,93 so com o Cubiomes e 0,92 gerada (lago congelado redondo, raio ~170, 100% de neve). A variante do prompt do juiz esta em `docs/juiz-prompt.md`.

```
python seed_hunter.py --garimpar 12 --amostra 5000 --tipo bacia
```

### Jogar a seed no Minecraft

O botão "Jogar no Minecraft" do inspetor mostra o comando, ou rode direto:

```
python seed_hunter.py --jogar 12345
```

Copia o mundo já gerado para `%APPDATA%\.minecraft\saves\SeedHunter_<seed>` (ou outra pasta com `--saves`). No Minecraft 26.3, abra Um jogador e procure por `SeedHunter_<seed>`. Fora da área gerada o jogo continua gerando o mesmo terreno. Se o mundo já existir lá, o script não sobrescreve (seu progresso fica seguro); `--forcar` recopia e apaga o progresso. Cada mundo ocupa cerca de 60 MB.

### Cavernas (raio-X), sob demanda

Um segundo mapa com as cavernas abertas custa uns 5 min e ~200 MB por seed, então só é gerado para as seeds que você escolher:

```
python seed_hunter.py --cavernas 12345 777
```

O botão "Cavernas" do inspetor só fica ativo nas seeds que já têm esse mapa.

## O que ele faz por seed

1. Sobe o Paper com a seed e roda cada regra de `LOCATE_RULES` medindo a distância a partir do **spawn** (o mesmo centro da área gerada). Falhou, a seed é `reprovada` em menos de um minuto.
2. Passou: Chunky pré-gera um quadrado de raio 480 centrado no spawn.
3. BlueMap renderiza o mapa e grava marcadores de spawn e achados.
4. O resultado vai para `resultados.csv`. Seeds `ok` e `reprovada` são puladas na próxima rodada; falhas são tentadas de novo, então pode interromper e continuar.

## Números medidos (PC de desenvolvimento)

Cerca de 120 MB por seed somando mundo e mapa. O tempo por seed aprovada (raio 480) caiu de 3,7 a 4,9 min para ~1,7 min depois de subir o render do BlueMap de 1 para 8 threads (`CORE_TWEAKS`; amostra pequena). Seeds reprovadas levam 0,2 a 0,4 min e nunca chegam ao BlueMap. A fase mais lenta é a renderização, não a geração (Chunky: ~26 s para 3.700 chunks). Rode 2 ou 3 seeds antes de uma rodada longa.

O pipeline sobrepõe as fases: enquanto o BlueMap renderiza a seed N, o Paper já filtra e gera a N+1 (um render por vez). Com isso o tempo registrado de cada seed no CSV inclui o que correu junto, então os minutos não somam o total da rodada; o total aparece no fim (`Rodada: N seeds em X min`). Para usar menos CPU, baixe `render-thread-count` em `CORE_TWEAKS`.

## Testes

```
python tests/test_seed_hunter.py
```

Cobrem o parser do `/locate` (com as linhas reais do Paper), do spawn, ids de pasta, leitura do `seeds.txt` e marcadores.

## Roteiro

- [x] Pipeline: filtro, Chunky, BlueMap, retomada
- [x] Interface: biblioteca com miniaturas e inspetor com iframe do BlueMap
- [x] Cavernas sob demanda
- [ ] Rodada longa com 30+ seeds
- [ ] Passada de design da interface (protótipo no canvas, depois ajustes no código)
- [ ] Gerar seeds e cavernas pela própria interface (hoje é só pela linha de comando)

## Licença

MIT. Minecraft é marca da Mojang/Microsoft; este projeto não é afiliado e não distribui arquivos do jogo.
