# Hospedagem gratuita do BN Bot na Oracle Cloud

Este caminho mantém o bot, a API, o dashboard, o PostgreSQL e o Redis em uma VM Linux. O PC não precisa permanecer ligado depois da implantação.

## Limites do plano gratuito

Use somente recursos marcados como Always Free. A cota elegível inclui até 2 OCPUs e 12 GB de RAM para Ampere A1 e até 200 GB de armazenamento em blocos na região principal. A Oracle exige, para a maioria das inscrições, telefone e cartão para verificação e informa que não cobra o cartão a menos que a conta seja atualizada. A disponibilidade da capacidade A1 pode variar. Instâncias Always Free consideradas ociosas durante sete dias podem ser recuperadas, então este plano não oferece garantia absoluta de disponibilidade permanente.

## Preparação da conta e da VM

1. Crie uma conta em https://www.oracle.com/cloud/free/ e escolha cuidadosamente a região principal.
2. No Compute, crie uma VM usando uma imagem Ubuntu LTS marcada como Always Free Eligible e a forma VM.Standard.A1.Flex, dentro do limite de 2 OCPUs e 12 GB de RAM.
3. Use um volume de inicialização de 50 GB ou outro tamanho dentro da cota Always Free.
4. Associe um endereço IPv4 público. Crie regras de entrada TCP para 22, 80 e 443 na lista de segurança da VCN ou no Network Security Group. Não abra as portas 5432 nem 6379.
5. Guarde a chave privada SSH baixada ao criar a VM. Nunca a envie ao GitHub.

## DNS e HTTPS

1. Crie um subdomínio gratuito em https://www.duckdns.org/.
2. Configure o endereço IPv4 público da VM como o IP desse subdomínio.
3. Edite `.env.production` no servidor e defina `PUBLIC_DOMAIN` com o nome completo do subdomínio. O Caddy solicitará e renovará o certificado HTTPS quando o DNS e as portas 80 e 443 estiverem acessíveis.

## Instalar Docker no Ubuntu

Conecte por SSH e execute:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF2
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF2
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

## Publicar o projeto

Clone o repositório no servidor:

```sh
git clone https://github.com/ItzLuquinha/Brasil-novo-bot.git
cd Brasil-novo-bot
```

Se a configuração de implantação ainda não estiver no GitHub, copie para esse repositório os arquivos `docker-compose.production.yml`, `Caddyfile`, `.env.production.example`, `web/Dockerfile`, `web/nginx.conf` e este guia antes de continuar.

Crie o arquivo privado de ambiente:

```sh
cp .env.production.example .env.production
chmod 600 .env.production
openssl rand -hex 32
openssl rand -hex 24
nano .env.production
```

Use a primeira saída no `APP_SECRET_KEY` e a segunda no `POSTGRES_PASSWORD`. Preencha `PUBLIC_DOMAIN`, `DISCORD_TOKEN`, `DISCORD_CLIENT_ID` e `DISCORD_CLIENT_SECRET` com os valores da sua aplicação Discord. Não coloque valores reais em `.env.example`, `.env.production.example` ou qualquer arquivo versionado.

O valor `DISCORD_REDIRECT_URI` é gerado pela configuração como `https://SEU_DOMINIO/api/v1/auth/callback`. Cadastre essa URI exatamente na seção OAuth2 do Discord Developer Portal. A `DASHBOARD_URL` e o CORS serão configurados para o mesmo domínio HTTPS.

Inicie os serviços:

```sh
sudo docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
```

Confira o estado e os logs:

```sh
sudo docker compose --env-file .env.production -f docker-compose.production.yml ps
sudo docker compose --env-file .env.production -f docker-compose.production.yml logs --tail=100 bot api caddy migrate
```

Quando tudo estiver ativo, abra `https://SEU_DOMINIO`. O bot, a API e o dashboard reiniciarão automaticamente junto com o Docker. O PostgreSQL, o Redis e os certificados são armazenados em volumes persistentes.

## Firewall local opcional

Se o UFW estiver ativado no Ubuntu, permita o SSH e o HTTPS:

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

As regras de rede da Oracle também precisam permitir os mesmos acessos públicos.

## Atualizar o bot

Depois de enviar as alterações ao GitHub:

```sh
git pull
sudo docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
```

## Persistência e cobrança

O banco e o Redis usam volumes Docker, mas isso não substitui backups. Faça cópias de segurança periódicas dos dados do PostgreSQL e mantenha-as fora da VM. Confirme no console que todos os recursos têm a indicação Always Free Eligible e permaneça dentro dos limites gratuitos. Não atualize a conta para Pay As You Go se for requisito não haver cobranças.
