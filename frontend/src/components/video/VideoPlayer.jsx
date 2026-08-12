// video-engine-v3 · Le dispatcher multi-pipelines est supprimé.
// Le seul moteur vidéo restant est WHEP aiortc (RTSP-native).
// On ré-exporte `LivePlayer` sous le nom `VideoPlayer` pour préserver
// la compatibilité des ~10 imports frontend existants sans refactor massif.
import LivePlayer, { pipelineOf } from "./LivePlayer";

export { pipelineOf };
export default LivePlayer;
