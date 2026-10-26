# Build stage
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

# Serve stage
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
# Rendered to /etc/nginx/conf.d/default.conf at start (envsubst); the resolver comes from /etc/resolv.conf.
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    API_GATEWAY_HOST=api-gateway.flexascale-apps.svc.cluster.local

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
