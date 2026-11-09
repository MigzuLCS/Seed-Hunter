# Seed Hunter

> Projeto pessoal em andamento. Funciona na minha máquina; espere arestas.

Transforma uma lista de seeds de Minecraft Java em mapas 3D navegáveis no navegador, sem abrir o jogo. Para cada seed ele filtra com `/locate`, pré-gera 30 chunks (480 blocos) em volta de (0,0) e renderiza com o BlueMap. Você deixa rodando e volta para comparar.

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

Para ver os mapas: `cd bluemap && java -jar bluemap-cli.jar -w` e abra http://localhost:8100. Troque de seed no seletor de mapas; o spawn e os achados do `/locate` aparecem como marcadores.

## O que ele faz por seed

1. Sobe o Paper com a seed e roda cada regra de `LOCATE_RULES` medindo a distância a partir de **(0,0)** (não do spawn). Falhou, a seed é `reprovada` em menos de um minuto.
2. Passou: Chunky pré-gera um quadrado de raio 480 centrado em (0,0).
3. BlueMap renderiza o mapa e grava marcadores de spawn e achados.
4. O resultado vai para `resultados.csv`. Seeds `ok` e `reprovada` são puladas na próxima rodada; falhas são tentadas de novo, então pode interromper e continuar.

## Números medidos (PC de desenvolvimento)

2,7 a 4 minutos por seed aprovada (raio 480) e cerca de 120 MB por seed somando mundo e mapa. Rode 2 ou 3 seeds antes de uma rodada longa.

## Testes

```
python tests/test_seed_hunter.py
```

Cobrem o parser do `/locate` (com as linhas reais do Paper), do spawn, ids de pasta, leitura do `seeds.txt` e marcadores.

## Roteiro

- [x] Pipeline: filtro, Chunky, BlueMap, retomada
- [ ] Rodada longa com 30+ seeds
- [ ] Mais regras de estruturas e biomas, e marcadores por tipo
- [ ] Interface própria (biblioteca de seeds com print do spawn e inspeção)

## Licença

MIT. Minecraft é marca da Mojang/Microsoft; este projeto não é afiliado e não distribui arquivos do jogo.
