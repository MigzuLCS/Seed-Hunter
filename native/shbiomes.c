/* shbiomes.c - fachada minima sobre o cubiomes (fork xpple, MIT) para o Python chamar via ctypes.
 * Calcula biomas direto da seed, sem gerar chunks. Compilacao: native/build.ps1 */
#include <stdlib.h>
#include <string.h>
#include "generator.h"
#include "util.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#ifdef _MSC_VER
/* O cubiomes usa a funcao interna do GCC; o MSVC nao a tem. Equivalente com a instrucao POPCNT. */
#include <intrin.h>
int __builtin_popcountll(unsigned long long x) { return (int) __popcnt64(x); }
#endif

/* Versao 26.3 do cubiomes (o valor do enum MC_26_3). */
EXPORT int sh_mc_26_3(void) { return MC_26_3; }

/* Gerador para uma seed no overworld. Devolve NULL se faltar memoria. Libere com sh_free. */
EXPORT void *sh_new(int mc, unsigned long long seed)
{
    Generator *g = (Generator *) malloc(sizeof(Generator));
    if (!g) return NULL;
    setupGenerator(g, mc, 0);
    applySeed(g, DIM_OVERWORLD, (uint64_t) seed);
    return g;
}

EXPORT void sh_free(void *g) { free(g); }

/* Bioma em uma posicao. scale 1 = blocos, 4 = celulas de bioma (bloco >> 2). y no mesmo sistema. */
EXPORT int sh_biome_at(void *g, int scale, int x, int y, int z)
{
    return getBiomeAt((const Generator *) g, scale, x, y, z);
}

/* Grade de biomas num plano horizontal (w x h celulas, escala `scale`) na altura y. out[z*w + x]. 0 = ok. */
EXPORT int sh_biome_grid(void *g, int scale, int x0, int z0, int w, int h, int y, int *out)
{
    Range r = { scale, x0, z0, w, h, y, 1 };
    int *cache = allocCache((const Generator *) g, r);
    if (!cache) return -1;
    int rc = genBiomes((const Generator *) g, cache, r);
    if (rc == 0) memcpy(out, cache, (size_t) w * (size_t) h * sizeof(int));
    free(cache);
    return rc;
}

/* Aproximacao da altura da superficie (mapApproxHeight): x,z em celulas de 4 blocos (bloco >> 2). Preenche
 * y[w*h] (float) e, se ids nao for NULL, os biomas da superficie. Para a 1.18+ o valor vem do parametro de
 * profundidade do ruido de clima: e uma estimativa relativa, nao a altura exata. 0 = ok. */
EXPORT int sh_surface(void *g, int x, int z, int w, int h, float *y, int *ids)
{
    return mapApproxHeight(y, ids, (const Generator *) g, NULL, x, z, w, h);
}

/* Nome do bioma ("minecraft:..." sem o prefixo; formato do cubiomes). */
EXPORT const char *sh_biome_name(int mc, int id) { return biome2str(mc, id); }
