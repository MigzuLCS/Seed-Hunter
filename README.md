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
