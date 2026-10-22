FROM node:22-alpine AS build
WORKDIR /app
# The interface kit comes from a git reference. npm fetches such a dependency
# with the git binary, over SSH by default -- and a build container has no
# key, so the URL is rewritten to https before anything is fetched.
RUN apk add --no-cache git \
 && git config --global url."https://github.com/".insteadOf "ssh://git@github.com/"
COPY package*.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
