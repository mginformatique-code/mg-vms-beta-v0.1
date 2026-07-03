# --- Étape build : compile le frontend React (craco) ---
# node:20 (Debian) inclut les outils natifs (node-gyp) → build plus fiable
FROM node:20 AS build
WORKDIR /app

# L'URL du backend est figée au build (CRA/craco)
ARG REACT_APP_BACKEND_URL=http://localhost:8001
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --network-timeout 600000

COPY . .
RUN yarn build

# --- Étape runtime : Nginx sert le build statique ---
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
