# Caça Duplicados — encontre arquivos duplicados e libere espaço (Python)

Fotos copiadas três vezes "por garantia", o mesmo PDF baixado de novo, aquele vídeo que está no backup e também nos Downloads. O **caca-duplicados** compara o conteúdo dos arquivos (não o nome), mostra os grupos de cópias ordenados pelo espaço desperdiçado e, só se você pedir, move as cópias extras para uma pasta de quarentena, apaga ou troca por hardlinks.

Roda no Windows, macOS e Linux, funciona offline e não tem dependências além do Python.

## Recursos

- Compara pelo conteúdo: arquivos com nomes diferentes e conteúdo igual são encontrados.
- Rápido em pastas grandes: agrupa por tamanho, depois compara o começo e o fim (64 KB de cada lado) e só então calcula o hash completo (BLAKE2b) de quem sobrou.
- Ignora links simbólicos, arquivos vazios (opcional) e hardlinks que já apontam para o mesmo arquivo; avisa sobre arquivos que não deu para ler.
- Filtros: `--min-tamanho 1M` (aceita `K`, `M`, `G`, `KB`, `MB`, `GB` e vírgula, como `1,5M`), `--ignorar` com padrões (repetível) e `--extensoes jpg,png`.
- Relatório em texto, JSON ou CSV, com tamanhos no formato brasileiro ("1,5 MB") e o total que pode ser liberado.
- Ações opcionais, sempre com confirmação (ou `--sim`) e com `--simular` para ver antes:
  - `--mover-para PASTA`: a mais segura, guarda as cópias mantendo a estrutura de pastas;
  - `--apagar`;
  - `--hardlink`: troca as cópias por hardlinks (só no mesmo disco), o espaço volta e os arquivos continuam onde estavam.
- Escolha de qual cópia fica com `--manter`: `mais-antigo` (padrão), `mais-novo`, `caminho-curto` ou `primeiro`.
- Nunca remove a última cópia: uma cópia de cada grupo sempre fica, e tudo é conferido de novo (existência, tamanho e data) logo antes de agir.

## Instalação

```bash
pipx install git+https://github.com/micdog22/caca-duplicados
# ou
pip install git+https://github.com/micdog22/caca-duplicados
```

Requer Python 3.9 ou mais novo.

## Como usar

Procurar duplicados em uma ou mais pastas (nada é alterado):

```console
$ caca-duplicados Fotos Backup Downloads
Grupo 1 · 2 arquivos iguais de 700 MB · 700 MB desperdiçados
  cópia   Backup/aula 1.mp4  (01/05/2024 08:00)
  manter  Downloads/curso-aula-01.mp4  (05/02/2024 09:00)

Grupo 2 · 3 arquivos iguais de 4,2 MB · 8,4 MB desperdiçados
  manter  Fotos/2024/Praia/IMG_1042.jpg  (10/03/2024 15:30)
  cópia   Backup/Fotos antigas/IMG_1042.jpg  (02/06/2024 22:10)
  cópia   Downloads/IMG_1042 (1).jpg  (14/09/2024 11:05)

Grupo 3 · 2 arquivos iguais de 244,1 KB · 244,1 KB desperdiçados
  cópia   Downloads/contrato (2).pdf  (20/08/2024 17:46)
  manter  Downloads/contrato.pdf  (20/08/2024 17:45)

7 arquivos analisados: 3 grupos de duplicados, 4 cópias extras.
Espaço que pode ser liberado: 708,6 MB.
Ignorados: 1 vazio.
```

A marcação `manter` mostra qual cópia ficaria se você usar uma ação (pela estratégia `--manter`, padrão `mais-antigo`).

Ver o que aconteceria ao mover as cópias para uma quarentena, preferindo manter o que está em `Fotos`:

```console
$ caca-duplicados Fotos Backup Downloads --manter primeiro --mover-para Quarentena --simular
...
  moveria   Downloads/curso-aula-01.mp4 -> Quarentena/Downloads/curso-aula-01.mp4
  moveria   Backup/Fotos antigas/IMG_1042.jpg -> Quarentena/Backup/Fotos antigas/IMG_1042.jpg
  moveria   Downloads/IMG_1042 (1).jpg -> Quarentena/Downloads/IMG_1042 (1).jpg
  moveria   Downloads/contrato (2).pdf -> Quarentena/Downloads/contrato (2).pdf

Simulação: 4 cópias extras (708,6 MB); nada foi alterado.
```

Tirando o `--simular`, ele pede confirmação antes de mover:

```console
$ caca-duplicados Fotos Backup Downloads --manter primeiro --mover-para Quarentena
...
Mover 4 cópias extras (708,6 MB) para Quarentena? [s/N] s
Pronto: 4 cópias movidas para Quarentena (708,6 MB).
```

Confira a pasta `Quarentena` com calma e apague quando tiver certeza.

Outros exemplos:

```bash
# Só fotos com mais de 500 KB
caca-duplicados ~/Fotos --min-tamanho 500K --extensoes jpg,jpeg,heic,png

# Ignorando pastas e arquivos temporários, com relatório para planilha
caca-duplicados ~/Projetos --ignorar node_modules --ignorar .git --ignorar "*.tmp" -f csv > duplicados.csv

# JSON para scripts
caca-duplicados ~/Documentos --formato json

# Liberar espaço sem tirar nenhum arquivo do lugar (mesmo disco)
caca-duplicados ~/Fotos --hardlink

# Apagar as cópias extras, sem perguntar (cuidado!)
caca-duplicados ~/Downloads --apagar --sim
```

### Opções

| Opção | O que faz |
|---|---|
| `--min-tamanho TAM` | ignora arquivos menores que `TAM` (`500K`, `1,5M`, `2G`; 1 KB = 1024 bytes) |
| `--incluir-vazios` | também compara arquivos vazios |
| `--ignorar PADRÃO` | ignora arquivos ou pastas que casam com o padrão (`*.tmp`, `node_modules`, `fotos/*`); pode repetir |
| `--extensoes LISTA` | compara só estas extensões (`jpg,png`) |
| `-f`, `--formato texto\|json\|csv` | formato do relatório; o CSV usa `;` |
| `--manter ESTRATÉGIA` | `mais-antigo` (padrão), `mais-novo`, `caminho-curto` (menos pastas e nome mais curto) ou `primeiro` (primeira pasta informada; dentro dela, a mais antiga) |
| `--mover-para PASTA` | move as cópias extras para `PASTA/<nome da pasta analisada>/<caminho original>` |
| `--apagar` | apaga as cópias extras |
| `--hardlink` | troca as cópias extras por hardlinks da cópia mantida |
| `-n`, `--simular` | mostra o que seria feito, sem alterar nada |
| `-s`, `--sim` | não pede confirmação |

Os padrões de `--ignorar` não diferenciam maiúsculas e são comparados com o nome do arquivo, com cada pasta do caminho e com o caminho relativo inteiro.

Códigos de saída: `0` nenhum duplicado (ou ação concluída), `1` duplicados encontrados (ou ação cancelada/com erro), `2` uso incorreto. Assim dá para usar em scripts: `caca-duplicados pasta >/dev/null || echo "tem duplicados"`.

## Como funciona

1. **Tamanho:** só arquivos com exatamente o mesmo tamanho podem ser iguais, então quase tudo é descartado sem abrir nenhum arquivo.
2. **Hash parcial:** para os que sobraram, lê os primeiros e os últimos 64 KB. Arquivos de até 128 KB são lidos inteiros nesta etapa.
3. **Hash completo:** só quem empatou no parcial tem o conteúdo inteiro lido, com BLAKE2b (`hashlib`, da biblioteca padrão).
4. **Ações:** a cópia mantida é escolhida pela estratégia; as outras são movidas, apagadas ou trocadas por hardlinks. Antes de cada ação, a cópia mantida e a cópia extra são conferidas de novo; se algo mudou desde a análise, aquele arquivo fica como está. O hardlink é criado com um nome temporário e trocado de forma atômica, então o arquivo nunca deixa de existir.

Pastas sobrepostas (como `Fotos` e `Fotos/2024`) são analisadas uma vez só, e a pasta de `--mover-para` fica fora da análise.

Com `--hardlink`, todos os nomes passam a apontar para o mesmo conteúdo: editar um deles altera todos, e a data de modificação passa a ser a da cópia mantida.

> Arquivos apagados com `--apagar` não vão para a lixeira. Na dúvida, use `--mover-para` e apague a quarentena depois.

## Rodando a partir do código-fonte

```bash
git clone https://github.com/micdog22/caca-duplicados
cd caca-duplicados
PYTHONPATH=src python3 -m caca_duplicados ~/Downloads
```

## Testes

```bash
python3 -m unittest discover -s tests -v
```

Os testes criam pastas temporárias e nunca tocam nos seus arquivos.

## Contribuindo

Issues e pull requests são bem-vindos.

## Licença

MIT — veja [LICENSE](LICENSE).
