# Data flow: wind farm MQTT topics to the Fabric eventstream

`windfarm-to-fabric.template.json` is the Azure IoT Operations data flow that forwards the
wind farm topics from the local MQTT broker to the custom endpoint of the Fabric eventstream.
`infra/06-connect-edge-to-fabric.sh` fills in the two placeholders and applies it.

| Part | Setting |
|---|---|
| Source | Default endpoint (the local MQTT broker), six topic filters |
| Transformation | None. Messages are forwarded unchanged. |
| Destination | Data flow endpoint `fabric-eventstream` (Kafka protocol), topic = the eventstream's topic name |

The `_sim` and `_control` topics are not in the source list, so simulator commands and the
anomaly ground truth never leave the edge.

To change what is forwarded, edit the `dataSources` list and run step 6 again. To filter or
reshape messages at the edge, add a `BuiltInTransformation` operation between the source and
the destination; see "Create data flows in Azure IoT Operations" on Microsoft Learn.

## Data flow: commands from the Fabric eventstream to the control topic (Phase 5a)

`fabric-to-windfarm-control.template.json` is the way back. `infra/08-create-command-path.sh`
fills in its three placeholders and applies it.

| Part | Setting |
|---|---|
| Source | Data flow endpoint `fabric-commands` (Kafka protocol, with a consumer group): the custom endpoint that is the destination of the eventstream `WindFarmCommands` |
| Transformation | None |
| Destination | Default endpoint (the local MQTT broker), topic `contoso/windfarm/<site>/_control/request` |

The simulator accepts five commands on that topic (curtail, release, stop, start, reset) and
answers each on `…/_control/response/{requestId}`. The answer stays on the edge.

