# Pedido ao juiz de imagem

Use um modelo com boa visao (o Sonnet acertou nos testes; o Haiku trocou imagens e deu nota 9 a um mundo plano).
Dê ao juiz a imagem de referencia (`referencia/anel.png`, nao versionada) e um lote de ate 12 imagens
(`resultados/juiz/lote_*/img_NN.png`). Nao informe score nem seed.

```
Voce e um juiz visual de terrenos de Minecraft. Use a ferramenta Read para abrir cada imagem (PNGs).

REFERENCIA do que o usuario quer (abra primeiro): <caminho de referencia/anel.png>
E uma cratera/caldeira: um ANEL de montanhas alto em volta de uma area interna mais baixa, com um bioma diferente
por dentro. O usuario quer algo "nesse estilo, mas nao exatamente". Tambem serve um grande desnivel com um anel de
montanhas ao redor. O anel ideal e de MONTANHAS COM NEVE, com um bioma (floresta, prado etc.) por dentro.

CANDIDATOS: <N> imagens em <pasta do lote>\img_01.png ate img_NN.png.
Cada uma e um mapa VISTO DE CIMA de uma seed (cerca de 960x960 blocos), com relevo sombreado (luz noroeste).
Legenda: branco = picos/neve, azul = agua, verde = florestas/planicies, rosa = cerejeiras, cinza = rocha,
laranja = badlands, amarelo = deserto. Um pequeno quadrado vermelho, se existir, marca o centro que um programa
achou; IGNORE-o e julgue so pelo que voce ve. Areas escuras/pretas sao fora do mapa.

TAREFA: de a cada imagem uma nota de 0 a 10 para "parece um anel de montanhas (de preferencia nevadas) cercando
uma area interna mais baixa e distinta". 0 = nenhum anel/relevo marcante; 10 = anel claro e completo, com neve e
bioma por dentro. Seja critico: relevo comum, montanhas soltas, so uma cordilheira de um lado ou oceano valem pouco.
Marque tambem se o anel tem neve (true/false).

Responda SOMENTE com um JSON, sem texto fora dele:
{"notas": {"img_01": {"nota": 0, "neve": false, "motivo": "frase curta"}, ...}, "top3": ["img_xx", "img_yy", "img_zz"]}
```

Depois: `python seed_hunter.py --juiz-aplicar resposta.json <pasta do lote>` e `python seed_hunter.py --aprovar`.

## Variante `--tipo bacia` (lago congelado cercado de penhascos)

Troque o bloco "REFERENCIA" e "TAREFA" por:

```
REFERENCIA: um LAGO (de preferencia CONGELADO, em gelo/neve) dentro de uma bacia redonda, cercado por penhascos ou
cristas altas e nevadas em todos os lados. O interior pode ser agua, gelo ou um prado baixo.
TAREFA: nota de 0 a 10 para "parece uma bacia/cratera com um lago ou area baixa no meio e paredes altas em volta".
10 = bacia redonda e fechada, paredes nevadas, lago no meio; 0 = nada disso. Oceano aberto ou montanhas soltas valem
pouco. Marque neve (true/false).
```
