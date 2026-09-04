# Dashboard de voos SIROS/ANAC

Projeto para consultar a API pública da SIROS (ANAC), persistir os voos no Supabase e exibir um recorte local em `index.html`.

## Como executar

Requer Python 3.10 ou superior. A URL padrão do coletor é `https://sas.anac.gov.br/sas/siros_api/api/voosPeriodo`, serviço documentado pela ANAC com os parâmetros `dataReferenciaInicio` e `dataReferenciaFinal`. Como a ANAC pode alterar o caminho ou os parâmetros publicados, ela pode ser substituída sem alterar o código:

```powershell
$env:SUPABASE_URL = "https://seu-projeto.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY = "sua-chave-service-role"
python scripts/fetch_flights.py
python -m http.server 8000
```

Abra `http://localhost:8000`. O navegador precisa acessar a página por HTTP para carregar `data/flights.json`; abrir o HTML diretamente como arquivo pode bloquear essa leitura.

O período padrão vai de hoje até 30 dias à frente. O coletor converte as datas ISO para o formato `ddmmyyyy` exigido pela SIROS. Para consultar outro intervalo:

```powershell
python scripts/fetch_flights.py --start-date 2026-09-01 --end-date 2026-09-30
```

Variáveis: `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` são obrigatórias para persistir no banco; `SIROS_API_URL`, `SIROS_API_TOKEN`, `SIROS_START_DATE` e `SIROS_END_DATE` são opcionais. Para rodar apenas o cache local, use `python scripts/fetch_flights.py --skip-supabase`.

## Arquivos

- `scripts/fetch_flights.py`: consulta, normaliza e faz upsert no Supabase, além de gerar caches JSON e SQLite.
- `sql/setup.sql`: esquema PostgreSQL e política de leitura para o Supabase.
- `data/airports.json`: cadastro inicial de aeroportos brasileiros para filtros e enriquecimentos futuros.
- `data/flights.json`: saída consumida pelo dashboard.
- `data/flights.db`: banco local regenerável.
- `.github/workflows/update flights.yml`: atualização diária e execução manual pelo GitHub Actions.

## Supabase

1. Crie um projeto no Supabase e execute `sql/setup.sql` no **SQL Editor**.
2. Copie a URL do projeto e a chave `service_role` em **Settings > API**.
3. Nunca coloque a chave `service_role` no HTML ou no repositório.

O coletor usa `POST /rest/v1/flights` com `resolution=merge-duplicates`, usando a restrição única da rota e do horário para atualizar registros sem duplicá-los. A política permite leitura pública; a chave `service_role` é usada somente no coletor. O arquivo `data/flights.json` também registra `pipeline.completed_at`, `pipeline.airports`, `pipeline.batches`, `pipeline.errors` e `pipeline.status` para o painel de acompanhamento.

## GitHub Actions

O workflow executa às 06:15 UTC e também pode ser disparado manualmente. Cadastre `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` como secrets. Se necessário, defina `SIROS_API_URL` como variable e `SIROS_API_TOKEN` como secret. O workflow precisa de permissão de escrita no conteúdo do repositório para publicar os caches atualizados.

Os nomes dos campos podem variar conforme a versão publicada da API. O coletor aceita respostas em lista ou dentro de `data`, `dados`, `results`, `resultados`, `items` ou `voos`, além dos nomes mais comuns dos campos de voo.